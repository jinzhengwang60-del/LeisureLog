"""Official game analytics; receives detached projections, owns no persistence."""

from datetime import date

from leisurelog.plugin_api import (
    AnalysisRejected,
    AnalysisResult,
    AnalyticsContribution,
    GameTypeChange,
    JsonSnapshot,
    PageContribution,
    PluginContributions,
    PluginPermission,
    resolve_game_type,
    type_options,
    validate_choice,
)

LABELS = {item["id"]: item["label"] for item in type_options()}


def decorate(item):
    item["game_type"] = resolve_game_type(item.pop("source_tags"), item.pop("type_override"))
    return item


def serializable(value):
    if type(value) is date:
        return value.isoformat()
    if type(value) is dict:
        return {key: serializable(child) for key, child in value.items()}
    if type(value) is list:
        return [serializable(child) for child in value]
    return value


METRICS = (
    "active_seconds",
    "recorded_seconds",
    "afk_seconds",
    "unverified_seconds",
    "detected_afk_seconds",
    "retained_afk_seconds",
)


def preferences(data, start: date, end: date) -> dict:
    if end < start or (end - start).days >= 3660:
        raise AnalysisRejected("日期需按先后排列，范围最多 3660 天")
    totals = dict.fromkeys(METRICS, 0)
    types, months, games = {}, {}, {}
    activity_months = {day.strftime("%Y-%m") for day in data["activity_days"]}

    def add(row, primary):
        genre = types.setdefault(
            primary,
            {
                "primary": primary,
                "label": LABELS[primary],
                **dict.fromkeys(METRICS, 0),
                "games": set(),
            },
        )
        month = months.setdefault(
            row["month"], {"has_game_records": True, **dict.fromkeys(METRICS, 0), "types": {}}
        )
        part = month["types"].setdefault(
            primary, {"primary": primary, "label": LABELS[primary], **dict.fromkeys(METRICS, 0)}
        )
        for metric in METRICS:
            totals[metric] += row[metric]
            genre[metric] += row[metric]
            month[metric] += row[metric]
            part[metric] += row[metric]
        return genre

    for row in data["rows"]:
        item = data["games"][row["key"]]
        primary = item["game_type"]["primary"]
        add(row, primary)["games"].add(row["key"])
        game = games.setdefault(
            row["key"],
            {
                "key": row["key"],
                "name": item["name"],
                "game_type": item["game_type"],
                **dict.fromkeys(METRICS, 0),
            },
        )
        for metric in METRICS:
            game[metric] += row[metric]
    for row in data["unnamed"]:
        add(row, "unknown")
    for genre in types.values():
        genre["game_count"] = len(genre.pop("games"))
        genre["share"] = (
            genre["active_seconds"] / totals["active_seconds"] if totals["active_seconds"] else None
        )
    cursor, trend = start.replace(day=1), []
    while cursor <= end:
        period = cursor.strftime("%Y-%m")
        month = months.get(
            period, {"has_game_records": False, **dict.fromkeys(METRICS, 0), "types": {}}
        )
        parts = list(month.pop("types").values())
        for part in parts:
            part["share"] = (
                part["active_seconds"] / month["active_seconds"]
                if month["active_seconds"]
                else None
            )
        trend.append(
            {
                "month": period,
                "has_activity_records": period in activity_months,
                **month,
                "types": sorted(parts, key=lambda p: (-p["active_seconds"], p["primary"])),
            }
        )
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return {
        "start": start,
        "end": end,
        "timezone": "Asia/Shanghai",
        "totals": totals,
        "coverage": {
            "activity_days": len(data["activity_days"]),
            "game_days": len(data["game_days"]),
            "first_game_day": min(data["game_days"], default=None),
            "last_game_day": max(data["game_days"], default=None),
        },
        "recorded_games": len(games),
        "unnamed_seconds": sum(r["active_seconds"] for r in data["unnamed"]),
        "untyped_seconds": types.get("unknown", {}).get("active_seconds", 0),
        "types": sorted(types.values(), key=lambda p: (-p["active_seconds"], p["primary"])),
        "games": sorted(games.values(), key=lambda g: (-g["active_seconds"], g["key"])),
        "trend": trend,
        "scope": (
            "按当前主类型回看历史；每段游戏活动只计一次，"
            "未知类型和未命名游戏包含在总量。缺少记录不表示没有游玩，尚未跨设备排重。"
        ),
    }


class GameAnalysis:
    def __init__(self, view):
        self.view = view

    def run(self, request):
        parameters, data = request.parameters.value(), request.data.value()
        if self.view == "options":
            result = {"types": type_options()}
        elif self.view == "listing":
            query = parameters["query"].strip().casefold()
            items = [decorate(item) for item in data["items"] if query in item["name"].casefold()]
            if parameters["scope"] == "tracked":
                items = [i for i in items if i["sessions"] or (i["installed"] and i["matches"])]
            elif parameters["scope"] == "recorded":
                items = [i for i in items if i["sessions"]]
            items.sort(key=lambda i: (i["name"].casefold(), i["key"]))
            items.sort(
                key=lambda i: (
                    (i["last_seen"] or "")
                    if parameters["sort"] == "recent"
                    else i["active_seconds"]
                ),
                reverse=True,
            )
            limit, offset = parameters["limit"], parameters["offset"]
            result = {
                "items": items[offset : offset + limit],
                "total": len(items),
                "recorded_games": sum(bool(i["sessions"]) for i in items),
                "active_seconds": sum(i["active_seconds"] for i in items),
                "limit": limit,
                "offset": offset,
            }
        elif self.view == "detail":
            decorate(data["item"])
            result = data
        elif self.view == "preferences":
            for item in data["games"].values():
                decorate(item)
            for field in ("activity_days", "game_days"):
                data[field] = [date.fromisoformat(value) for value in data[field]]
            result = preferences(
                data, date.fromisoformat(parameters["start"]), date.fromisoformat(parameters["end"])
            )
        elif self.view in ("save", "reset"):
            body = parameters.get("body", {})
            if self.view == "reset":
                change = GameTypeChange(parameters["key"])
            else:
                try:
                    tags = validate_choice(body["primary"], body["tags"])
                except ValueError as error:
                    raise AnalysisRejected(str(error)) from None
                change = GameTypeChange(parameters["key"], body["primary"], tuple(tags))
            return AnalysisResult(change=change)
        else:
            raise AnalysisRejected("未知分析", 404)
        return AnalysisResult(JsonSnapshot.from_value(serializable(result)))


def create(context):
    read = (PluginPermission.GAME_STATISTICS_READ,)
    details = (*read, PluginPermission.DETAILS_READ)
    write = (*details, PluginPermission.GAME_TYPES_WRITE)
    return PluginContributions(
        analytics=tuple(
            AnalyticsContribution(view, GameAnalysis(view), permissions)
            for view, permissions in (
                ("listing", read),
                ("detail", details),
                ("preferences", read),
                ("options", ()),
                ("save", write),
                ("reset", write),
            )
        ),
        pages=(
            PageContribution(
                "games",
                "游戏",
                "game-statistics.html",
                (
                    "game-statistics.html",
                    "game-statistics.js",
                    "game-statistics.css",
                    "game-access.js",
                ),
            ),
            PageContribution(
                "preferences",
                "类型与偏好",
                "game-preferences.html",
                (
                    "game-preferences.html",
                    "game-preferences.js",
                    "game-preferences.css",
                    "game-access.js",
                ),
            ),
        ),
    )
