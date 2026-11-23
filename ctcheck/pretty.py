"""Pretty-printer from AST back to CT-IMP source (fully parenthesised)."""

from __future__ import annotations

from typing import List

from . import ast as A


def expr(e: A.Expr) -> str:
    if isinstance(e, A.IntLit):
        return str(e.value) if e.value >= 0 else f"(0 - {-e.value})"
    if isinstance(e, A.Var):
        return e.name
    if isinstance(e, A.Len):
        return f"len({e.array})"
    if isinstance(e, A.Index):
        return f"{e.array}[{expr(e.index)}]"
    if isinstance(e, A.BinOp):
        return f"({expr(e.left)} {e.op} {expr(e.right)})"
    if isinstance(e, A.UnOp):
        return f"({e.op}{expr(e.operand)})"
    if isinstance(e, A.Select):
        return f"select({expr(e.cond)}, {expr(e.then)}, {expr(e.other)})"
    raise TypeError(e)  # pragma: no cover


def stmts(ss: List[A.Stmt], indent: int = 0) -> List[str]:
    pad = "  " * indent
    out: List[str] = []
    for s in ss:
        if isinstance(s, A.Skip):
            out.append(f"{pad}skip;")
        elif isinstance(s, A.Assign):
            out.append(f"{pad}{s.target} := {expr(s.value)};")
        elif isinstance(s, A.ArrayAssign):
            out.append(f"{pad}{s.array}[{expr(s.index)}] := {expr(s.value)};")
        elif isinstance(s, A.If):
            out.append(f"{pad}if ({expr(s.cond)}) {{")
            out += stmts(s.then, indent + 1)
            if s.other:
                out.append(f"{pad}}} else {{")
                out += stmts(s.other, indent + 1)
            out.append(f"{pad}}}")
        elif isinstance(s, A.For):
            out.append(f"{pad}for {s.var} in {expr(s.lo)} .. {expr(s.hi)} {{")
            out += stmts(s.body, indent + 1)
            out.append(f"{pad}}}")
        else:  # pragma: no cover
            raise TypeError(s)
    return out


def decl(d: A.Decl) -> str:
    if isinstance(d, A.ScalarDecl):
        init = f" = {d.init}" if d.init is not None else ""
        return f"{d.label.value} int {d.name}{init};"
    init = " = {" + ", ".join(map(str, d.init)) + "}" if d.init is not None else ""
    return f"{d.label.value} int[{d.size}] {d.name}{init};"


def program(p: A.Program) -> str:
    return "\n".join([decl(d) for d in p.decls] + [""] + stmts(p.body)) + "\n"
