from pathlib import Path

from app.api.system import health
from app.version import __version__


def test_release_identity_is_centralized():
    payload = health()
    assert __version__ == "1.4.9"
    assert payload["status"] == "ok"
    assert payload["version"] == __version__
    assert payload["edition"]


def test_shared_web_assets_reference_current_release():
    repository_root = Path(__file__).resolve().parents[2]
    index = (repository_root / "web" / "index.html").read_text(encoding="utf-8")
    assert "ReelIndex 1.4.9" in index
    assert "?v=1.4.9" in index


def test_docker_workflow_runs_the_complete_backend_suite():
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / ".github" / "workflows" / "docker.yml").read_text(
        encoding="utf-8"
    )
    assert "Run full backend test suite" in workflow
    assert "pytest -q" in workflow
