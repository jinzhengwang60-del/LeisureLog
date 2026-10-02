"""Conservative title extraction independent of websites, storage and HTTP."""

import re


class TitleContentExtractor:
    def __init__(self, pattern: str):
        self.pattern = re.compile(pattern)
        if "content" not in self.pattern.groupindex:
            raise ValueError("Content title pattern must have a named content group")

    def extract(self, title: str) -> str | None:
        # Watcher titles are untrusted; use bounded input and full matches only.
        if len(title) > 1000:
            return None
        match = self.pattern.fullmatch(title)
        if match is None:
            return None
        value = " ".join((match.group("content") or "").split())
        return value if 0 < len(value) <= 300 else None
