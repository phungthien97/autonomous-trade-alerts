from app.audit import AuditLog


def test_append_two_events_and_grow(tmp_path) -> None:
    path = tmp_path / "nested" / "events.jsonl"
    log = AuditLog(path)
    log.append("intent", {"symbol": "AAPL"})
    log.append("fill", {"symbol": "AAPL", "qty": 1})
    rows = log.read_all()
    assert [row["event_type"] for row in rows] == ["intent", "fill"]
    assert rows[0]["payload"]["symbol"] == "AAPL"
    assert "ts" in rows[1]
    size_after_two = path.stat().st_size
    log.append("fee", {"total": 0.35})
    assert path.stat().st_size > size_after_two
    assert len(log.read_all()) == 3
