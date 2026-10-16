# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Validate the documentation conventions required by the Orbit repository."""

from __future__ import annotations

import ast
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = (ROOT / "src", ROOT / "tests", ROOT / "examples", ROOT / "scripts")
MARKDOWN_ROOTS = (ROOT,)
GENERATED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".config",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
GENERATED_PYTHON_FILES = frozenset(
    {
        "process_plugin_pb2.py",
        "process_plugin_pb2_grpc.py",
        "stream_processing_pb2.py",
    }
)
LOCAL_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
FORBIDDEN_COMMENT_MARKERS = re.compile(r"\b(?:TODO|FIXME|XXX|HACK|WIP)\b", re.IGNORECASE)


def python_files() -> list[Path]:
    """Return maintained Orbit CLI Python files under documentation policy."""
    return sorted(
        path
        for base in PYTHON_ROOTS
        for path in base.rglob("*.py")
        if not GENERATED_DIRECTORIES.intersection(path.parts)
        and path.name not in GENERATED_PYTHON_FILES
    )


def markdown_files() -> list[Path]:
    """Return Orbit CLI Markdown, excluding generated environments."""
    return sorted(
        path
        for base in MARKDOWN_ROOTS
        for path in base.rglob("*.md")
        if not GENERATED_DIRECTORIES.intersection(path.parts)
    )


def public_api_roots() -> tuple[Path, ...]:
    """Return this package's import root whose public API requires docstrings."""
    return (ROOT / "src" / "orbit_cli",)


def public_documentation_errors(path: Path, tree: ast.Module) -> list[str]:
    """Return missing module, class, or public callable docstrings for one Python file."""
    errors: list[str] = []
    if not ast.get_docstring(tree):
        errors.append(f"{path}: missing module docstring")

    def visit_class(node: ast.ClassDef) -> None:
        if not node.name.startswith("_") and not ast.get_docstring(node):
            errors.append(f"{path}:{node.lineno}: public class {node.name} lacks a docstring")
        for child in node.body:
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not child.name.startswith("_")
                and not ast.get_docstring(child)
            ):
                errors.append(
                    f"{path}:{child.lineno}: public method {child.name} lacks a docstring"
                )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and not ast.get_docstring(node):
                errors.append(
                    f"{path}:{node.lineno}: public function {node.name} lacks a docstring"
                )
        elif isinstance(node, ast.ClassDef):
            visit_class(node)
    return errors


def comment_errors(path: Path) -> list[str]:
    """Return stale-work markers found in Python comments."""
    errors: list[str] = []
    with path.open("rb") as stream:
        for token in tokenize.tokenize(stream.readline):
            if token.type == tokenize.COMMENT and FORBIDDEN_COMMENT_MARKERS.search(token.string):
                errors.append(f"{path}:{token.start[0]}: unresolved marker in comment")
    return errors


def markdown_errors(path: Path) -> list[str]:
    """Return structural errors found in one Markdown document."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    errors: list[str] = []
    content = lines
    first_nonempty = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_nonempty is not None and lines[first_nonempty].strip() == "---":
        closing = next(
            (
                index
                for index in range(first_nonempty + 1, len(lines))
                if lines[index].strip() == "---"
            ),
            None,
        )
        if closing is not None:
            content = lines[closing + 1 :]
    first = next((line.strip() for line in content if line.strip()), "")
    if not first.startswith("# "):
        errors.append(f"{path}: document must begin with an H1 heading")
    if sum(line.strip().startswith("```") for line in lines) % 2:
        errors.append(f"{path}: unmatched fenced code block")
    for target in LOCAL_LINK.findall(text):
        target = target.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (path.parent / target).resolve().exists():
            errors.append(f"{path}: local link does not exist: {target}")
    return errors


def main() -> int:
    """Validate source docstrings, comment hygiene, Markdown structure, and local links."""
    errors: list[str] = []
    documented_roots = public_api_roots()
    for path in python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{path}:{exc.lineno}: invalid Python syntax")
            continue
        if any(path.is_relative_to(root) for root in documented_roots):
            errors.extend(public_documentation_errors(path, tree))
        errors.extend(comment_errors(path))
    for path in markdown_files():
        errors.extend(markdown_errors(path))
    if errors:
        print("Documentation policy violations:", file=sys.stderr)
        print("\n".join(f"  {error}" for error in errors), file=sys.stderr)
        return 1
    print("Documentation checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
