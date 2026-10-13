from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from leisurelog.domain.learned_rules import match_value


def make_engine(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        raise ValueError("Phase 1 supports SQLite only")
    if parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.create_function(
            "leisurelog_casefold", 1, lambda value: (value or "").casefold(), deterministic=True
        )
        connection.create_function(
            "leisurelog_hostname",
            1,
            lambda value: match_value(SimpleNamespace(url=value), "domain"),
            deterministic=True,
        )
        connection.create_function(
            "leisurelog_url",
            1,
            lambda value: match_value(SimpleNamespace(url=value), "url"),
            deterministic=True,
        )

    return engine


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
