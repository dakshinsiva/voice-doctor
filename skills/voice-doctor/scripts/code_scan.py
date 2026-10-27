"""Read voice-agent settings out of Python source (LiveKit Agents, Pipecat).

Parses files with the standard library's ast module (never imports or runs
them) and returns every constructor-style call with its keyword arguments,
literal values where they are literal, and line numbers, plus string literals
that look like the system prompt and first message.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field

class Expr(str):
    """Source text of an argument that isn't a literal (a variable, call or env lookup)."""


@dataclass
class Call:
    name: str  # dotted, e.g. "AgentSession", "silero.VAD.load", "deepgram.STT"
    file: str
    line: int
    kwargs: dict = field(default_factory=dict)  # name -> literal value, or Expr(source) if not literal
    args: list = field(default_factory=list)  # positional arguments, same treatment
    kw_lines: dict = field(default_factory=dict)

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    def has(self, key: str) -> bool:
        return key in self.kwargs

    def get(self, key: str, default=None):
        return self.kwargs.get(key, default)


@dataclass
class Source:
    files: list[str]
    calls: list[Call]
    imports: set[str]
    strings: list[tuple[str, int, str]]  # (file, line, text) of string literals 40+ chars long

    def find(self, *names: str) -> list[Call]:
        wanted = set(names)
        return [c for c in self.calls if c.name in wanted or c.short in wanted]

    def framework(self) -> str:
        if any(i.startswith("livekit") for i in self.imports):
            return "livekit"
        if any(i.startswith("pipecat") for i in self.imports):
            return "pipecat"
        return "unknown"


def dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    if isinstance(node, ast.Call):
        return dotted(node.func)
    return ""


class _Inline(ast.NodeTransformer):
    """Replace names of module-level literal constants with their values."""

    def __init__(self, constants: dict):
        self.constants = constants

    def visit_Name(self, node):
        if node.id in self.constants:
            return ast.copy_location(ast.Constant(self.constants[node.id]), node)
        return node


def value_of(node, text: str, constants: dict | None = None):
    if constants:
        import copy
        node = _Inline(constants).visit(copy.deepcopy(node))
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        pass
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        try:
            return -ast.literal_eval(node.operand)
        except (ValueError, SyntaxError, TypeError):
            pass
    return Expr(ast.get_source_segment(text, node) or "?")


def python_files(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", ".venv", "node_modules", "__pycache__", "site-packages")]
                out += sorted(os.path.join(root, f) for f in files if f.endswith(".py"))
        elif p.endswith(".py"):
            out.append(p)
    return out


def scan(paths: list[str]) -> Source:
    files = python_files(paths)
    calls, imports, strings = [], set(), []
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            tree = ast.parse(text, filename=path)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        constants = {}
        for node in tree.body:  # module-level NAME = "literal" (prompts are often kept this way)
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    v = ast.literal_eval(node.value)
                except (ValueError, SyntaxError, TypeError):
                    continue
                if isinstance(v, (str, int, float, bool)):
                    constants[node.targets[0].id] = v
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                name = dotted(node.func)
                if not name:
                    continue
                c = Call(name=name, file=path, line=node.lineno, args=[value_of(a, text, constants) for a in node.args])
                for kw in node.keywords:
                    if kw.arg:
                        c.kwargs[kw.arg] = value_of(kw.value, text, constants)
                        c.kw_lines[kw.arg] = kw.value.lineno
                calls.append(c)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 40:
                strings.append((path, node.lineno, node.value))
    return Source(files=files, calls=calls, imports=imports, strings=strings)


def is_literal(v) -> bool:
    return not isinstance(v, Expr)
