"""Conservative source dependency identities for deterministic local strategies.

Static imports include package initializers. Dynamic code/import discovery disables
result reuse rather than pretending to prove a complete dependency graph. Explicit
cache_dependencies and path-valued parameters capture non-Python inputs.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any


def _hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def dependency_manifest(root: Path, factory: str, spec: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    source = root / 'src'
    modules = {}
    for path in (source / 'n225m_bt').rglob('*.py'):
        relative = path.relative_to(source).with_suffix('')
        name = '.'.join(relative.parts)
        if name.endswith('.__init__'):
            name = name[:-9]
        modules[name] = path
    seeds = ['n225m_bt.research.runner', 'n225m_bt.research.dependencies', factory.partition(':')[0]]
    visited: set[str] = set()
    pending = list(seeds)
    warnings: list[str] = []
    literals: set[str] = set()
    cacheable = True
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        path = modules.get(name)
        if path is None:
            if name.startswith('n225m_bt.'):
                warnings.append(f'unresolved local module: {name}')
                cacheable = False
            continue
        visited.add(name)
        for i in range(1, len(name.split('.'))):
            parent = '.'.join(name.split('.')[:i])
            if parent in modules:
                pending.append(parent)
        try:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        except SyntaxError:
            cacheable = False
            warnings.append(f'unparseable source: {name}')
            continue
        strategy_code = name.startswith(('n225m_bt.strategies.', 'n225m_bt.components.'))
        dynamic_aliases = {'__import__', 'eval', 'exec', 'import_module'}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for item in node.names:
                    if item.name in {'import_module', 'spec_from_file_location'}:
                        dynamic_aliases.add(item.asname or item.name)
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        for node in ast.walk(tree):
            if strategy_code and isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names if alias.name.startswith('n225m_bt'))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split('.')
                    prefix = '.'.join(parts[:len(parts) - node.level + 1])
                    base = '.'.join(filter(None, [prefix, node.module]))
                else:
                    base = node.module or ''
                if base.startswith('n225m_bt'):
                    pending.append(base)
                    pending.extend(f'{base}.{alias.name}' for alias in node.names
                                   if f'{base}.{alias.name}' in modules)
                if strategy_code and any(a.name == '*' for a in node.names):
                    cacheable = False
                    warnings.append(f'wildcard import in {name}')
            elif strategy_code and isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
                if called in dynamic_aliases | {'exec_module', 'spec_from_file_location', 'iter_modules'}:
                    cacheable = False
                    warnings.append(f'dynamic code/import in {name}')
    paths = [modules[name] for name in visited]
    if not cacheable:
        paths = list(modules.values())
    code = {p.relative_to(root).as_posix(): _hash(p) for p in sorted(paths)}
    resources: dict[str, str] = {}
    candidates = set(spec.get('cache_dependencies', []))
    def walk(value: Any, key: str = '') -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and key.endswith(('_path', '_file')):
            candidates.add(value)
    walk(spec.get('parameters', {}))
    walk(spec.get('space', {}))
    walk(spec.get('variants', []))
    for value in literals:
        if '\n' not in value and len(value) < 300 and value.endswith(('.yaml', '.yml', '.json', '.toml')):
            candidate = root / value
            if candidate.is_file():
                candidates.add(value)
    for value in sorted(candidates):
        path = (root / value).resolve()
        key = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        if path.is_file():
            resources[key] = _hash(path)
        else:
            resources[key] = 'MISSING'
            cacheable = False
            warnings.append(f'missing declared resource: {value}')
    return {'code': code, 'resources': resources, 'cacheable': cacheable,
            'warnings': sorted(set(warnings)), 'identity_version': 2}
