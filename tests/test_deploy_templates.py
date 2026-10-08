from pathlib import Path


def test_gateway_templates_exist() -> None:
    root = Path(__file__).resolve().parents[1] / "deploy" / "ibgateway"
    for name in ("README.md", "ibgateway.service", "live-worker.service", "live-worker.timer", "live-audit.logrotate"):
        assert (root / name).is_file()
