"""Configuration failures preserve the last file; stale writes do not win."""

import os

import pytest

from leisurelog.domain.plugin_runtime import PluginConfiguration
from leisurelog.domain.plugins import PluginPermission
from leisurelog.repositories.plugin_state import FilePluginState, PluginConfigurationConflict


def test_roundtrip_and_stale_revision_preserve_configuration(tmp_path):
    store = FilePluginState(tmp_path / "config" / "plugins.json")
    assert store.load().revision == 0
    value = PluginConfiguration(1, {"example.summary": (PluginPermission.SUMMARY_READ,)})
    store.save(value, expected_revision=0)
    assert store.load() == value
    original = store.path.read_bytes()
    with pytest.raises(PluginConfigurationConflict):
        store.save(PluginConfiguration(1), expected_revision=0)
    assert store.path.read_bytes() == original


def test_failed_atomic_replace_keeps_original_and_removes_temporary_file(tmp_path, monkeypatch):
    store = FilePluginState(tmp_path / "plugins.json")
    store.save(PluginConfiguration(1), expected_revision=0)
    original = store.path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save(PluginConfiguration(2, {"example.task": ()}), expected_revision=1)
    assert store.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize(
    "text",
    [
        '{"version":2,"revision":0,"enabled":{}}',
        '{"version":true,"revision":0,"enabled":{}}',
        '{"version":1,"revision":true,"enabled":{}}',
        '{"version":1,"revision":0,"enabled":{},"module":"arbitrary.py"}',
        '{"version":1,"revision":0,"enabled":{"core.bad":[]}}',
        '{"version":1,"revision":0,"enabled":{"example.bad":["database.write"]}}',
        '{"version":1,"revision":0,"enabled":{"example.bad":"activity.summary.read"}}',
        '{"version":1,"revision":0,"revision":1,"enabled":{}}',
    ],
)
def test_unknown_or_ambiguous_configuration_is_not_silently_rewritten(tmp_path, text):
    store = FilePluginState(tmp_path / "plugins.json")
    store.path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        store.load()
    assert store.path.read_text(encoding="utf-8") == text
