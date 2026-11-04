import ast
from pathlib import Path

import fontes

FORBIDDEN = {"fastapi", "sqlalchemy", "aio_pika", "anthropic", "ollama", "httpx", "asyncpg"}
INNER_LAYERS = ("domain", "application")


def _imported_top_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_inner_layers_do_not_import_frameworks() -> None:
    root = Path(fontes.__file__).parent
    violations = [
        f"{path.relative_to(root)}: {sorted(bad)}"
        for layer in INNER_LAYERS
        for path in (root / layer).rglob("*.py")
        if (bad := _imported_top_modules(path) & FORBIDDEN)
    ]
    assert violations == []
