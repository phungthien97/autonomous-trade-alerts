from app.paths import LivePaths, ROOT


def test_live_paths_default_under_repo() -> None:
    paths = LivePaths()
    assert paths.state_dir == ROOT / "state_live"
    assert paths.config_path.name == "config.json"
    assert paths.risk_path.name == "risk.json"
    assert paths.audit_log_path.name == "events.jsonl"


def test_live_paths_respect_project_root(tmp_path) -> None:
    paths = LivePaths(project_root=tmp_path)
    assert paths.state_dir == tmp_path / "state_live"
    assert paths.queue_path == tmp_path / "state_live" / "queue.json"
    assert paths.idempotency_path == tmp_path / "state_live" / "idempotency.json"
