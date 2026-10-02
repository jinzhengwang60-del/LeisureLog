"""Content identity is scoped, independent of display names and raw events."""

import json
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from leisurelog.domain.models import Session


@dataclass(frozen=True)
class ContentIdentity:
    app: str
    category: str
    name: str

    @property
    def id(self) -> str:
        key = json.dumps([self.app, self.category, self.name], ensure_ascii=False)
        return str(uuid5(NAMESPACE_URL, "leisurelog:content:" + key))


def identities(sessions: list[Session]) -> list[ContentIdentity]:
    return list(
        dict.fromkeys(
            ContentIdentity(s.app, s.classification.category, s.classification.content)
            for s in sessions
            if s.classification.content and s.classification.content.strip()
        )
    )
