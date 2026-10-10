import re
import unicodedata
from collections import defaultdict

from leisurelog.domain.ports import LibraryStore

SPACING = re.compile(r"[\s\u00b7\u30fb\-_:：·]+")


def same_name_key(name: str) -> str:
    """Names that only differ in width, case, spaces or separators ("棕色尘埃 2" / "棕色尘埃2")."""
    return SPACING.sub("", unicodedata.normalize("NFKC", name).casefold())


def duplicates(store: LibraryStore) -> list[dict]:
    """Items of one category whose names are the same apart from spacing and case. Each group
    proposes the item with the most time as the one to keep."""
    items = store.listing("", "", "time", 100_000, 0)["items"]
    groups = defaultdict(list)
    for item in items:
        groups[(item["category"], same_name_key(item["name"]))].append(item)
    result = []
    for (category, _), members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: (-item["active_seconds"], item["name"]))
        result.append({
            "category": category,
            "name": members[0]["name"],
            "target_id": members[0]["id"],
            "active_seconds": sum(item["active_seconds"] for item in members),
            "items": [
                {key: item.get(key) for key in ("id", "name", "apps", "active_seconds", "days")}
                for item in members
            ],
        })
    return sorted(result, key=lambda group: -group["active_seconds"])


def catalog(store: LibraryStore, query: str, category: str, sort: str, limit: int, offset: int):
    return store.listing(query.strip(), category, sort, limit, offset)


def content_detail(store: LibraryStore, item_id: str, limit: int, offset: int):
    return store.detail(item_id, limit, offset)
