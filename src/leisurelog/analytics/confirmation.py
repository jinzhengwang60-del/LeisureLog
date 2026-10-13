"""A dated, paginated review of purposes that are not yet known."""

from leisurelog.domain.learned_rules import is_browser


def validate_range(start, end):
    if end < start or (end - start).days >= 3660:
        raise ValueError("Date range must be ordered and at most 3660 days")


def pending_report(store, start, end, limit=40, offset=0, search=""):
    validate_range(start, end)
    facts = store.pending_facts(start, end, limit, offset, search)
    for item in facts["items"]:
        item["browser"] = is_browser(item["app"])
        title = item.pop("sample_title")
        item["sample_titles"] = [title] if title else []
    return {"start": start, "end": end, "limit": limit, "offset": offset, **facts}
