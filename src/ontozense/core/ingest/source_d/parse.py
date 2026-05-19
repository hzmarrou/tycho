"""Parse stage — read a Python file into AST plus a lightweight symbol/context map."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedModule:
    path: Path
    source: str
    tree: ast.Module
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    imports: set[str] = field(default_factory=set)


def parse_module(path: Path) -> ParsedModule:
    """Parse a Python source file into AST + a top-level symbol map.

    Scope: walks ``tree.body`` only. Nested classes/functions inside
    other classes are intentionally excluded — extractor families
    (Tasks 8–12) walk into class bodies themselves where needed.

    Raises:
        UnicodeDecodeError: if the file is not valid UTF-8.
        SyntaxError: if the source is not parseable Python.

    Both are propagated unwrapped; callers should decide how to
    surface them (the v1.1 SourceDIngester logs and skips).
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    pm = ParsedModule(path=path, source=source, tree=tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            pm.classes[node.name] = node
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pm.functions[node.name] = node
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pm.imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                pm.imports.add(node.module.split(".")[0])
    return pm
