"""AST-only discovery of reusable code; never imports or approves a component."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


def build_catalog(root: Path) -> dict[str, Any]:
    usage_file = root / ".research/component_usage.json"
    usage = json.loads(usage_file.read_text(encoding="utf-8")) if usage_file.exists() else {}
    references_file = root / ".research/component_references.json"
    references = json.loads(references_file.read_text(encoding="utf-8")) if references_file.exists() else {}
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    source = root / "src"
    for folder in (source / "n225m_bt/components", source / "n225m_bt/strategies"):
        for path in sorted(folder.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                warnings.append(f"{path.relative_to(root)}: {exc}")
                continue
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    name = decorator.func.id if isinstance(decorator.func, ast.Name) else ""
                    if name != "component":
                        continue
                    try:
                        metadata = {kw.arg: ast.literal_eval(kw.value) for kw in decorator.keywords}
                    except (ValueError, TypeError):
                        warnings.append(f"{path.name}:{node.lineno}: metadata must be literal")
                        continue
                    signature = node.name
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        signature += f"({ast.unparse(node.args)})"
                    elif isinstance(node, ast.ClassDef):
                        for member in node.body:
                            if isinstance(member, ast.FunctionDef) and member.name == "__init__":
                                signature += f"({ast.unparse(member.args)})"
                    entries.append(dict(metadata) | {
                        "symbol": path.relative_to(source).with_suffix("").as_posix().replace("/", ".") + ":" + node.name,
                        "path": path.relative_to(root).as_posix(), "signature": signature,
                        "doc": ast.get_docstring(node) or "",
                        "used_by_families": usage.get(metadata.get("id"), []),
                        "referenced_by_families": references.get(metadata.get("id"), []),
                        "code_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    })
    return {"components": entries, "warnings": warnings}
