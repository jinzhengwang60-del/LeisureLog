"""Project reports are derived from dated activity facts, never wall-clock project spans."""


def project_report(store, start, end, project_id=None):
    if end < start or (end - start).days >= 3660:
        raise ValueError("Date range must be ordered and at most 3660 days")
    facts = store.project_facts(start, end, project_id)
    projects = store.projects()
    by_id = {item["id"]: item for item in projects}
    if project_id is not None:
        store.project(project_id)
    totals = {"active_seconds": 0, "recorded_seconds": 0, "unverified_seconds": 0}
    unassigned = 0
    measures = {}
    for row in facts["projects"]:
        for key in totals:
            totals[key] += row[key] or 0
        if row["project_id"] is None:
            unassigned += row["active_seconds"] or 0
        else:
            measures[row["project_id"]] = row
    items = [
        {
            **item,
            **measures.get(
                item["id"],
                {
                    "active_seconds": 0,
                    "recorded_seconds": 0,
                    "unverified_seconds": 0,
                    "days": 0,
                    "sessions": 0,
                },
            ),
        }
        for item in projects
        if project_id is None or item["id"] == project_id
    ]
    items.sort(
        key=lambda item: (item["archived"], -item["active_seconds"], item["name"], item["id"])
    )
    return {
        "start": start,
        "end": end,
        "totals": totals,
        "unassigned_seconds": unassigned,
        "items": items,
        "apps": facts["apps"],
        "purposes": facts["purposes"],
        "days": sorted(facts["days"], key=lambda row: row["day"]),
        "project": by_id.get(project_id),
        "timezone": "Asia/Shanghai",
    }
