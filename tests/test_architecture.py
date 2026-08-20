import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "getcourse_downloader"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_domain_does_not_depend_on_frameworks_or_outer_layers():
    forbidden = (
        "aiohttp",
        "flet",
        "playwright",
        "subprocess",
        "getcourse_downloader.application",
        "getcourse_downloader.infrastructure",
        "getcourse_downloader.presentation",
    )
    for path in (PACKAGE_ROOT / "domain").rglob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), path


def test_application_does_not_depend_on_infrastructure_or_ui():
    forbidden = (
        "aiohttp",
        "flet",
        "playwright",
        "subprocess",
        "getcourse_downloader.infrastructure",
        "getcourse_downloader.presentation",
    )
    for path in (PACKAGE_ROOT / "application").rglob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), path
