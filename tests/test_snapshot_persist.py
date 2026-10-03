"""The snapshot survives a deploy and is never read half-written (3 Oct)."""

import json
import os

import snapshot as S


def test_persist_is_write_then_rename(tmp_path, monkeypatch):
    target = tmp_path / "snapshot_state.json"
    monkeypatch.setattr(S, "SNAPSHOT_FILE", str(target))
    S._persist({"generated_at": "2026-10-03T17:00:00+10:00", "ok": True})
    assert json.loads(target.read_text())["ok"] is True
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot_state.json"]  # no tmp left


def test_snapshot_lives_on_the_volume_when_one_is_mounted():
    import config
    src = open(config.__file__, encoding="utf-8").read()
    assert '"/data/snapshot_state.json"' in src
    if not os.getenv("SNAPSHOT_FILE") and not os.path.isdir("/data"):
        assert config.SNAPSHOT_FILE == "snapshot_state.json"
