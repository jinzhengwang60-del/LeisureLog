"""Reload config/rules.yaml without restarting, then reprocess history with it."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from leisurelog.adapters.rules import RuleClassifier
from leisurelog.domain.classification import ClassificationPipeline
from leisurelog.repositories.sqlite import SQLiteRepository
from leisurelog.services.processing import ProcessingService

router = APIRouter()


@router.post("/api/classification/reload-rules")
def reload_rules(request: Request):
    state = request.app.state
    try:
        rules = RuleClassifier(state.settings.rules_path)
    except Exception as exc:  # YAML, validation, regex or file errors: keep the old rules.
        detail = f"Rules file is invalid; previous rules stay active: {exc}"
        raise HTTPException(422, detail) from exc
    pipeline = ClassificationPipeline([rules], rules.timing_rules, [rules])
    job = getattr(getattr(state, "scheduler", None), "run", None)
    previous = state.pipeline
    with state.sessions() as db:
        # Swap while holding the write lock so a waiting sync never mixes old and new rules.
        db.execute(text("BEGIN IMMEDIATE"))
        try:
            result = ProcessingService(
                SQLiteRepository(db), pipeline, state.settings.session_gap_seconds
            ).rebuild()
            state.pipeline = pipeline
            if hasattr(job, "pipeline"):
                job.pipeline = pipeline
            db.commit()
        except Exception:
            db.rollback()
            state.pipeline = previous
            if hasattr(job, "pipeline"):
                job.pipeline = previous
            raise
    return {**result, "rules": len(rules.rules), "timing_rules": len(rules.timing_rules)}
