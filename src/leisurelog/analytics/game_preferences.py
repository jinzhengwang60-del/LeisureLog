from datetime import date

from leisurelog.domain.game_types import LABELS
from leisurelog.domain.ports import GamePreferencesStore

METRICS = (
    "active_seconds",
    "recorded_seconds",
    "afk_seconds",
    "unverified_seconds",
    "detected_afk_seconds",
    "retained_afk_seconds",
)


def preferences(store: GamePreferencesStore, start: date, end: date) -> dict:
    if end < start or (end - start).days >= 3660:
        raise ValueError("日期需按先后排列，范围最多 3660 天")
    data = store.preference_facts(start, end)
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
