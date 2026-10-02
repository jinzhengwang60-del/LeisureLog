from datetime import timedelta

from tests.test_pipeline import ROOT, START, WINDOW

pytest_plugins = ["tests.test_pipeline"]


def test_reload_rules_reclassifies_and_keeps_old_rules_on_error(app_context, tmp_path):
    client, app, payloads, _, _ = app_context
    payloads.append(
        {
            "id": 3,
            "timestamp": (START + timedelta(minutes=10)).isoformat(),
            "duration": 60,
            "data": {"app": "Weixin.exe", "title": "微信"},
        }
    )
    client.post("/api/sync/activitywatch", json=WINDOW).raise_for_status()
    rules = tmp_path / "rules.yaml"
    original = (ROOT / "config/rules.yaml").read_text(encoding="utf-8")
    rules.write_text(original, encoding="utf-8")
    app.state.settings.rules_path = rules

    def weixin():
        return next(e for e in client.get("/api/events").json() if e["app"] == "Weixin.exe")

    assert weixin()["classification"]["category"] == "unknown"
    rules.write_text(
        original.replace(
            "rules:\n",
            "rules:\n  - id: wechat\n    match: {app: Weixin.exe}\n    category: social\n",
            1,
        ),
        encoding="utf-8",
    )
    reloaded = client.post("/api/classification/reload-rules")
    assert reloaded.status_code == 200, reloaded.text
    assert weixin()["classification"] == {**weixin()["classification"], "category": "social",
                                          "origin": "rule:wechat"}
    # The background sync job uses the same, new pipeline.
    assert app.state.scheduler.run.pipeline is app.state.pipeline

    # A broken file is rejected and the active rules stay in place.
    active = app.state.pipeline
    rules.write_text("rules: [\n", encoding="utf-8")
    broken = client.post("/api/classification/reload-rules")
    assert broken.status_code == 422
    assert app.state.pipeline is active
    client.post("/api/reprocess").raise_for_status()
    assert weixin()["classification"]["category"] == "social"
