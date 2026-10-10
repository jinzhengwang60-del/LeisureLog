"""Read-only view of activity that no rule or correction has classified yet."""

from dataclasses import asdict

from leisurelog.domain.app_suggestions import suggest
from leisurelog.domain.learned_rules import is_browser


def unclassified_report(repo, limit: int = 200) -> dict:
    apps = repo.unclassified_apps(limit)
    for item in apps:
        item["browser"] = is_browser(item["app"])
        guess = None if item["browser"] else suggest(item["app"], item["sample_titles"])
        item["suggestion"] = asdict(guess) if guess else None
    return {
        "total_active_seconds": sum(item["active_seconds"] for item in apps),
        "app_count": sum(1 for item in apps if not item["browser"]),
        "browser_active_seconds": sum(item["active_seconds"] for item in apps if item["browser"]),
        "suggested_count": sum(1 for item in apps if item["suggestion"]),
        "apps": apps,
    }
