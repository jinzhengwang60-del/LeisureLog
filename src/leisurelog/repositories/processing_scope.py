"""SQL interval planning: expand changes through current windows and old Sessions.

Old Sessions close over former membership when a heartbeat shrinks or moves.
Ignoring classification boundaries is conservative: connected activity can be
larger than the changed Session, but never cuts a possible merge at its boundary.
"""

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import and_, false, func, or_, select

from leisurelog.domain.processing import coalesce
from leisurelog.repositories.models import ActivityEventRow, SessionRow


def condition(table, scope, *, streams=True):
    return (
        or_(
            *[
                and_(
                    table.source == r.source,
                    table.device == r.device,
                    *([table.stream == r.stream] if streams and r.stream is not None else []),
                    table.start_time <= r.end,
                    table.end_time >= r.start,
                )
                for r in scope
            ]
        )
        if scope
        else false()
    )


def query(table, *, scope=None, start=None, end=None, ids=None, limit=None, offset=0, streams=True):
    statement = select(table).order_by(table.start_time, table.id)
    if scope is not None:
        statement = statement.where(condition(table, scope, streams=streams))
    if start is not None:
        statement = statement.where(table.end_time > start)
    if end is not None:
        statement = statement.where(table.start_time < end)
    if ids is not None:
        statement = statement.where(table.id.in_(ids))
    if limit is not None:
        statement = statement.limit(limit)
    return statement.offset(offset) if offset else statement


def plan(db, changes, gap_seconds):
    seeds = []
    for value in coalesce(changes, gap_seconds):
        if value.stream is not None:
            seeds.append(value)
        else:
            # Web/AFK records can affect all window streams on the same device.
            streams = set()
            for table in (ActivityEventRow, SessionRow):
                streams.update(
                    db.scalars(
                        select(table.stream)
                        .where(condition(table, [value], streams=False))
                        .distinct()
                    )
                )
            seeds.extend(replace(value, stream=stream) for stream in sorted(streams))
    expanded = []
    gap = timedelta(seconds=gap_seconds)
    for value in coalesce(seeds, gap_seconds):
        while True:
            nearby = replace(value, start=value.start - gap, end=value.end + gap)
            starts, ends = [value.start], [value.end]
            for table in (ActivityEventRow, SessionRow):
                low, high = db.execute(
                    select(func.min(table.start_time), func.max(table.end_time)).where(
                        condition(table, [nearby])
                    )
                ).one()
                if low is not None:
                    starts.append(low)
                    ends.append(high)
            next_value = replace(value, start=min(starts), end=max(ends))
            if value == next_value:
                break
            value = next_value
        expanded.append(value)
    return coalesce(expanded, gap_seconds)
