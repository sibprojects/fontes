import ast
from pathlib import Path

import fontes

FORBIDDEN = {"fastapi", "sqlalchemy", "aio_pika", "anthropic", "ollama", "httpx", "asyncpg"}
INNER_LAYERS = ("domain", "application")
ROOT = Path(fontes.__file__).parent


def _module_name(path: Path) -> str:
    parts = ("fontes", *path.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_modules(path: Path) -> set[str]:
    """Full dotted names of every module the file imports; relative imports are resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _violations(layers: tuple[str, ...], forbidden: set[str]) -> list[str]:
    def is_forbidden(name: str) -> bool:
        return any(name == f or name.startswith(f + ".") for f in forbidden)

    return [
        f"{path.relative_to(ROOT)}: {sorted(bad)}"
        for layer in layers
        for path in (ROOT / layer).rglob("*.py")
        if (bad := {n for n in _imported_modules(path) if is_forbidden(n)})
    ]


def test_inner_layers_do_not_import_frameworks() -> None:
    assert _violations(INNER_LAYERS, FORBIDDEN) == []


def test_inner_layers_do_not_import_outer_layers() -> None:
    outer = {"fontes.adapters", "fontes.api", "fontes.container", "fontes.main"}
    assert _violations(INNER_LAYERS, outer) == []


def test_api_does_not_import_adapters() -> None:
    assert _violations(("api",), {"fontes.adapters", "fontes.container"}) == []
