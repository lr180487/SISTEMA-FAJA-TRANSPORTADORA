from pathlib import Path

from backend.core.config import BASE_DIR, settings


def test_backend_config_resolves_project_root_and_frontend() -> None:
    project_root = Path(__file__).resolve().parents[1]

    assert BASE_DIR == project_root
    assert settings.base_dir == project_root
    assert settings.frontend_dir == project_root / "frontend"
    assert (settings.frontend_dir / "index.html").is_file()
    assert (settings.frontend_dir / "app.js").is_file()
    assert settings.agents_dir == project_root / "agents"
    assert settings.knowledge_dir == project_root / "knowledge_base"
