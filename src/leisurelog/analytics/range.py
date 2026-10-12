from datetime import date, timedelta

LEISURE_CATEGORIES = frozenset(
    {
        "game",
        "video",
        "film",
        "anime",
        "reading",
        "music",
        "social",
        "live",
        "browsing",
    }
)


def statistics(repo, start: date, end: date, granularity: str, purpose="", project_id="") -> dict:
    if end < start or (end - start).days >= 3660:
        raise ValueError("Date range must be ordered and at most 3660 days")
    if granularity == "auto":
        granularity = "month" if (end - start).days >= 90 else "day"
    result = repo.range_statistics(start, end, granularity, purpose, project_id)
    result["project_options"] = repo.projects()
    result["totals"]["purpose_unknown_seconds"] = sum(
        row["active_seconds"] for row in result["purposes"] if row["purpose"] == "unknown"
    )
    result["filters"] = {"purpose": purpose, "project_id": project_id}
    result["totals"]["confirmed_seconds"] = max(
        0, result["totals"]["active_seconds"] - result["totals"]["unverified_seconds"]
    )
    result["totals"]["leisure_seconds"] = sum(
        row["active_seconds"]
        for row in result["categories"]
        if row["category"] in LEISURE_CATEGORIES
    )
    result["totals"]["unknown_seconds"] = sum(
        row["active_seconds"] for row in result["categories"] if row["category"] == "unknown"
    )
    result["totals"]["work_seconds"] = sum(
        row["active_seconds"] for row in result["categories"] if row["category"] == "work"
    )
    buckets = {row["period"]: row for row in result.pop("trend")}
    cursor = start.replace(day=1) if granularity == "month" else start
    trend = []
    while cursor <= end:
        key = cursor.strftime("%Y-%m" if granularity == "month" else "%Y-%m-%d")
        trend.append(
            {
                "period": key,
                "has_records": key in buckets,
                **{
                    name: buckets.get(key, {}).get(name, 0)
                    for name in [
                        "recorded_seconds",
                        "active_seconds",
                        "afk_seconds",
                        "detected_afk_seconds",
                        "retained_afk_seconds",
                        "unverified_seconds",
                    ]
                },
            }
        )
        if granularity == "month":
            cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        else:
            cursor += timedelta(days=1)
    return {
        "start": start,
        "end": end,
        "timezone": "Asia/Shanghai",
        "granularity": granularity,
        **result,
        "trend": trend,
        "scope": (
            "configured timing policy applied; detected AFK preserved; "
            "unknown coverage retained; no cross-stream dedup"
        ),
        "leisure_categories": sorted(LEISURE_CATEGORIES),
    }
