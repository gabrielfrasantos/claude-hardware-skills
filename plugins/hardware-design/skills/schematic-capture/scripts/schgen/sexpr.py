"""Minimal S-expression reader/writer for KiCad files.

Atoms keep their raw text. Strings are wrapped in Str so they are written back quoted.
"""


class Str(str):
    pass


class Sym(str):
    pass


def parse(text):
    tokens = _tokens(text)
    stack, current = [], []
    for token in tokens:
        if token == "(":
            stack.append(current)
            current = []
        elif token == ")":
            done = current
            current = stack.pop()
            current.append(done)
        else:
            current.append(token)
    return current[0]


def _tokens(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == '"':
            j, out = i + 1, []
            while text[j] != '"':
                if text[j] == "\\":
                    out.append({"n": "\n", "t": "\t"}.get(text[j + 1], text[j + 1]))
                    j += 2
                else:
                    out.append(text[j])
                    j += 1
            yield Str("".join(out))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            yield Sym(text[i:j])
            i = j


def _atom(value):
    if isinstance(value, Str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text
    return str(value)


def dump(node, indent=0):
    if not isinstance(node, list):
        return _atom(node)
    if all(not isinstance(child, list) for child in node):
        return "(" + " ".join(_atom(child) for child in node) + ")"
    pad = "\t" * (indent + 1)
    parts = ["(" + " ".join(_atom(c) for c in _head(node))]
    for child in node[len(_head(node)):]:
        parts.append("\n" + pad + dump(child, indent + 1))
    parts.append("\n" + "\t" * indent + ")")
    return "".join(parts)


def _head(node):
    head = []
    for child in node:
        if isinstance(child, list):
            break
        head.append(child)
    return head


def find(node, key):
    for child in node:
        if isinstance(child, list) and child and child[0] == key:
            return child
    return None


def find_all(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]
