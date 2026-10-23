"""Read and write KiCad's s-expression files.

A parsed file is a tree of ``list`` nodes. Unquoted atoms (keywords and numbers)
are ``Sym``; quoted strings are plain ``str``. Keeping numbers as their original
text means a footprint read from a library is written back exactly as KiCad
wrote it, and ``num()`` formats the numbers we compute ourselves.

The writer is deterministic: the same tree always produces the same bytes.
"""

from __future__ import annotations

from collections.abc import Iterator

Node = list  # (head, *children); head is a Sym


class Sym(str):
    """An unquoted atom: a keyword or a number."""

    __slots__ = ()


def num(x: float) -> Sym:
    """Format a number the way KiCad does: up to 6 decimals, no trailing zeros."""
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return Sym("0" if s in ("-0", "") else s)


def _tokens(text: str) -> Iterator[str | Sym]:
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield Sym(c)
            i += 1
        elif c == '"':
            i += 1
            out = []
            while text[i] != '"':
                if text[i] == "\\":
                    i += 1
                    out.append({"n": "\n", "t": "\t"}.get(text[i], text[i]))
                else:
                    out.append(text[i])
                i += 1
            i += 1
            yield "".join(out)
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield Sym(text[i:j])
            i = j


def parse(text: str) -> Node:
    """Parse one top-level s-expression."""
    stack: list[Node] = []
    for tok in _tokens(text):
        if isinstance(tok, Sym) and tok == "(":
            stack.append([])
        elif isinstance(tok, Sym) and tok == ")":
            node = stack.pop()
            if not stack:
                return node
            stack[-1].append(node)
        else:
            stack[-1].append(tok)
    raise ValueError("unbalanced s-expression")


def _atom(a: str) -> str:
    if isinstance(a, Sym):
        return a
    esc = a.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{esc}"'


def dumps(node: Node, indent: int = 0) -> str:
    """Serialise a node, KiCad-style: one child list per line, tab-indented."""
    first_list = next((i for i, a in enumerate(node) if isinstance(a, list)), len(node))
    head = "(" + " ".join(_atom(a) for a in node[:first_list])
    rest = node[first_list:]
    if not rest:
        return head + ")"
    pad = "\t" * (indent + 1)
    body = "\n".join(
        pad + (dumps(k, indent + 1) if isinstance(k, list) else _atom(k)) for k in rest
    )
    return f"{head}\n{body}\n" + "\t" * indent + ")"


def find(node: Node, key: str) -> Node | None:
    """First child list whose head is *key*."""
    return next((c for c in node if isinstance(c, list) and c and c[0] == key), None)


def find_all(node: Node, key: str) -> list[Node]:
    return [c for c in node if isinstance(c, list) and c and c[0] == key]
