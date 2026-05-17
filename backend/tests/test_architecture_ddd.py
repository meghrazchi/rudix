from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"


def _python_files(base: Path) -> list[Path]:
    return sorted(path for path in base.rglob("*.py") if "__pycache__" not in path.parts)


def test_legacy_horizontal_layers_are_removed() -> None:
    # DDD structure should use app/domains and shared modules, not horizontal service/repo/schema folders.
    assert not (APP_DIR / "services").exists()
    assert not (APP_DIR / "repositories").exists()
    assert not (APP_DIR / "schemas").exists()


def test_no_legacy_layer_imports_remain() -> None:
    forbidden_tokens = tuple(f"app.{layer}" for layer in ("services", "repositories", "schemas"))
    offenders: list[str] = []
    for file_path in _python_files(PROJECT_ROOT / "app"):
        content = file_path.read_text()
        for token in forbidden_tokens:
            if token in content:
                offenders.append(f"{file_path.relative_to(PROJECT_ROOT)} -> {token}")
    for file_path in _python_files(PROJECT_ROOT / "tests"):
        if file_path.name == "test_architecture_ddd.py":
            continue
        content = file_path.read_text()
        for token in forbidden_tokens:
            if token in content:
                offenders.append(f"{file_path.relative_to(PROJECT_ROOT)} -> {token}")

    assert not offenders, "Legacy horizontal-layer imports found:\n" + "\n".join(offenders)


def test_domain_layer_has_no_http_api_modules() -> None:
    offenders = sorted((APP_DIR / "domains").glob("*/api/*.py"))
    assert not offenders, "HTTP modules should live under app/interfaces/http, not app/domains/*/api"


def test_api_router_uses_interface_routers() -> None:
    router_file = APP_DIR / "api" / "router.py"
    content = router_file.read_text()
    assert "from app.interfaces.http import (" in content
    assert "admin," in content
    assert "auth," in content
    assert "chat," in content
    assert "documents," in content
    assert "evaluation_sets," in content
    assert "evaluations," in content
    assert "pipeline," in content
    assert "team," in content
    assert "api_router.include_router(auth.router)" in content
    assert "protected_router.include_router(documents.router)" in content
    assert "protected_router.include_router(chat.router)" in content
    assert "protected_router.include_router(evaluation_sets.router)" in content
    assert "protected_router.include_router(evaluations.router)" in content
    assert "protected_router.include_router(pipeline.router)" in content
    assert "protected_router.include_router(admin.router)" in content
    assert "protected_router.include_router(team.router)" in content
