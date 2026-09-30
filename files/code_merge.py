"""Put an upgrade the model wrote into the current file.

Small models seldom rewrite a whole file faithfully: they send the functions they changed,
often without their class, sometimes with `...` for what they left alone. A complete new
version replaces the file; anything less is merged in: each definition replaces the one with
the same name (a method goes back into its class), new ones are added and the rest is kept.
"""
import ast

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINITIONS = FUNCTIONS + (ast.ClassDef,)


class MergeError(Exception):
    """The new code can't be put into the file."""


def names(node):
    """The names a statement defines: a function or class, or the variables it assigns."""
    if isinstance(node, DEFINITIONS):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def members(node):
    """{name: statement} for what a module or class body defines."""
    return {name: item for item in node.body for name in names(item)}


def definitions(tree):
    """{name: statement} for what other files can use: top-level names and Class.member."""
    found = {}
    for name, node in members(tree).items():
        found[name] = node
        if isinstance(node, ast.ClassDef):
            found.update({f"{name}.{member}": item for member, item in members(node).items()})
    return found


def docstring(node):
    first = node.body[0] if node.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return first
    return None


def placeholder(node):
    """A function whose body is only a docstring, `pass` or `...`: the model's "unchanged"."""
    if not isinstance(node, FUNCTIONS):
        return False
    body = node.body[1:] if docstring(node) else node.body
    return all(isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                                           and s.value.value is Ellipsis) for s in body)


def is_method(node):
    """A function written as a method: it takes self or cls, or is a static/class method."""
    if not isinstance(node, FUNCTIONS):
        return False
    decorators = {d.id for d in node.decorator_list if isinstance(d, ast.Name)}
    return (bool(node.args.args) and node.args.args[0].arg in ("self", "cls")
            or bool(decorators & {"staticmethod", "classmethod"}))


def span(node):
    """First and last line of a statement (1-based), decorators included."""
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]), node.end_lineno


def fit(old_code, new_code):
    """(code, changed, left_out): the file after the upgrade.

    changed is None when new_code replaces the whole file, else the names put in. The result
    still defines everything old_code did, or MergeError is raised.
    """
    new = ast.parse(new_code)
    try:
        old = ast.parse(old_code)
    except SyntaxError:
        return new_code, None, []  # the current file is broken anyway
    old_defs, new_defs = definitions(old), definitions(new)
    stubs = [name for name, node in new_defs.items()
             if placeholder(node) and name in old_defs and not placeholder(old_defs[name])]
    if old_defs.keys() <= new_defs.keys() and not stubs:
        return new_code, None, []

    code, changed, left_out = Merge(old_code, old, new_code, new).run()
    if not changed:
        raise MergeError("nothing in the new code fits into the file" +
                         (". Left out: " + "; ".join(left_out) if left_out else ""))
    try:
        lost = sorted(old_defs.keys() - definitions(ast.parse(code)).keys())
    except SyntaxError as e:
        raise MergeError(f"the new code doesn't fit into the file ({e})") from e
    if lost:
        raise MergeError("the file would lose " + ", ".join(lost[:10]) + (" ..." if len(lost) > 10 else ""))
    return code, changed, left_out


class Merge:
    """Puts each definition of the new code in place of the old one with the same name."""

    def __init__(self, old_code, old, new_code, new):
        self.lines, self.new_lines = old_code.splitlines(), new_code.splitlines()
        self.old, self.new = old, new
        self.top = members(old)
        self.classes = [node for node in old.body if isinstance(node, ast.ClassDef)]
        # Class members and functions inside functions, by name: the model often sends them alone
        self.methods, self.nested = {}, {}
        direct = {id(node) for node in self.top.values()}
        for cls in self.classes:
            for name, item in members(cls).items():
                self.methods.setdefault(name, []).append((cls, item))
                direct.add(id(item))
        for node in ast.walk(old):
            if isinstance(node, FUNCTIONS) and id(node) not in direct:
                self.nested.setdefault(node.name, []).append(node)
        self.edits = []  # (start, end, order, lines, name): lines replace self.lines[start:end]
        self.left_out = []

    def run(self):
        for node in self.new.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.add_import(node)
            elif isinstance(node, ast.ClassDef) and isinstance(self.top.get(node.name), ast.ClassDef):
                self.merge_class(self.top[node.name], node)
            elif names(node):
                self.put(node, names(node)[0])
            # other statements (example calls, tests) are left out
        return self.apply()

    def put(self, node, name):
        if name in self.top:
            return self.replace(self.top[name], node, name)
        methods = self.methods.get(name, [])
        if methods:
            if len(methods) > 1:
                return self.left_out.append(f"{name}, which several classes have")
            cls, method = methods[0]
            if not is_method(node) and isinstance(method, FUNCTIONS):
                return self.left_out.append(f"{name}, a method of {cls.name} sent without self")
            return self.replace(method, node, name)
        nested = self.nested.get(name, [])
        if nested and not is_method(node):
            if len(nested) > 1:
                return self.left_out.append(f"{name}, which is defined in several places")
            return self.replace(nested[0], node, name)
        if is_method(node):
            if len(self.classes) != 1:
                return self.left_out.append(f"{name}, a method with no class to put it in")
            return self.add_member(self.classes[0], node, name)
        if isinstance(node, DEFINITIONS) or name.isupper():
            return self.add_top(node, name)
        # a new lower-case variable at the top level is usually example code: left out

    def merge_class(self, old_cls, new_cls):
        doc, old_doc = docstring(new_cls), docstring(old_cls)
        if doc and old_doc:
            self.replace(old_doc, doc, f"{old_cls.name} docstring")
        elif doc:
            first = old_cls.body[0]
            self.insert(span(first)[0] - 1, self.text(doc, first.col_offset), f"{old_cls.name} docstring")
        old_members = members(old_cls)
        for item in new_cls.body:
            for name in names(item)[:1]:
                if name in old_members:
                    self.replace(old_members[name], item, name)
                else:
                    self.add_member(old_cls, item, name)

    def add_member(self, cls, node, name):
        if placeholder(node):
            return self.left_out.append(f"{name}, sent only as a placeholder")
        self.insert(cls.end_lineno, [""] + self.text(node, cls.body[0].col_offset), name)

    def add_top(self, node, name):
        if placeholder(node):
            return self.left_out.append(f"{name}, sent only as a placeholder")
        text = self.text(node, 0)
        if not isinstance(node, DEFINITIONS):  # a new setting goes with the others at the top
            return self.insert(self.header_end(), text, name)
        main = next((n for n in self.old.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)), None)
        if main:
            self.insert(span(main)[0] - 1, text + ["", ""], name)
        else:
            self.insert(len(self.lines), ["", ""] + text, name)

    def add_import(self, node):
        line = ast.unparse(node)
        if line not in {ast.unparse(n) for n in self.old.body if isinstance(n, (ast.Import, ast.ImportFrom))}:
            self.insert(self.header_end(), [line], line)

    def header_end(self):
        """Index of the line after the docstring, imports and settings at the top of the old file."""
        end = 0
        for node in self.old.body:
            if not (isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign))
                    or isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                break
            end = node.end_lineno
        return end

    def text(self, node, indent):
        """The new code's lines for a statement, moved to start at column `indent`."""
        first, last = span(node)
        shift = indent - node.col_offset
        moved = []
        for line in self.new_lines[first - 1:last]:
            if shift >= 0:
                moved.append(" " * shift + line if line.strip() else line)
            else:
                moved.append(line[min(-shift, len(line) - len(line.lstrip(" "))):])
        return moved

    def replace(self, old_node, new_node, name):
        if placeholder(new_node) and not placeholder(old_node):
            return self.left_out.append(f"{name}, sent only as a placeholder")
        first, last = span(old_node)
        lines = self.text(new_node, old_node.col_offset)
        if lines != self.lines[first - 1:last]:
            self.edits.append((first - 1, last, len(self.edits), lines, name))

    def insert(self, index, lines, name):
        self.edits.append((index, index, len(self.edits), lines, name))

    def apply(self):
        """(code, changed, left_out). A definition inside a bigger one that is also replaced
        comes with the bigger one; the same one sent twice counts once."""
        chosen = []
        for edit in sorted(self.edits, key=lambda e: e[0] - e[1]):  # biggest replacements first
            if not any(overlap(edit, other) for other in chosen):
                chosen.append(edit)
        lines = list(self.lines)
        for start, end, _, new, _ in sorted(chosen, key=lambda e: e[:3], reverse=True):
            lines[start:end] = new
        changed = list(dict.fromkeys(e[4] for e in sorted(chosen, key=lambda e: e[2])))
        return "\n".join(lines) + "\n", changed, self.left_out


def overlap(a, b):
    (s1, e1), (s2, e2) = a[:2], b[:2]
    if s1 == e1:
        return s2 < s1 < e2  # an insertion inside a replaced part
    if s2 == e2:
        return s1 < s2 < e1
    return s1 < e2 and s2 < e1
