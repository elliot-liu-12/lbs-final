"""Lark-based parser producing :mod:`ctcheck.ast` nodes."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken

from . import ast as A

GRAMMAR_PATH = Path(__file__).with_name("grammar.lark")


class ParseError(Exception):
    def __init__(self, message: str, loc: A.Loc = A.NO_LOC):
        super().__init__(f"{loc}: {message}" if loc != A.NO_LOC else message)
        self.loc = loc
        self.message = message


@lru_cache(maxsize=1)
def _lark() -> Lark:
    return Lark(
        GRAMMAR_PATH.read_text(),
        start="program",
        parser="lalr",
        propagate_positions=True,
    )


def _loc(obj) -> A.Loc:
    if isinstance(obj, Token):
        return A.Loc(obj.line or 0, obj.column or 0)
    meta = getattr(obj, "meta", obj)
    if getattr(meta, "empty", True):
        return A.NO_LOC
    return A.Loc(meta.line, meta.column)


def _int(tok) -> int:
    text = str(tok)
    neg = text.startswith("-")
    body = text[1:] if neg else text
    v = int(body, 16) if body[:2].lower() == "0x" else int(body, 10)
    return -v if neg else v


@v_args(meta=True)
class _ToAst(Transformer):
    # -------------------------------------------------------------- program
    def program(self, meta, children):
        decls = [c for c in children if isinstance(c, (A.ScalarDecl, A.ArrayDecl))]
        body = [c for c in children if not isinstance(c, (A.ScalarDecl, A.ArrayDecl))]
        return A.Program(decls, body)

    def scalar_decl(self, meta, children):
        label_tok, name_tok, *rest = children
        init = _int(rest[0]) if rest else None
        return A.ScalarDecl(A.Label(str(label_tok)), str(name_tok), init, _loc(label_tok))

    def array_decl(self, meta, children):
        label_tok, size_tok, name_tok, *rest = children
        init = rest[0] if rest else None
        return A.ArrayDecl(A.Label(str(label_tok)), str(name_tok), int(size_tok), init, _loc(label_tok))

    def int_list(self, meta, children):
        return [_int(c) for c in children]

    # -------------------------------------------------------------- statements
    def assign(self, meta, children):
        name, value = children
        return A.Assign(str(name), value, _loc(name))

    def array_assign(self, meta, children):
        name, index, value = children
        return A.ArrayAssign(str(name), index, value, _loc(name))

    def if_stmt(self, meta, children):
        if_tok, cond, then = children[:3]
        other: List[A.Stmt] = []
        if len(children) == 5:  # IF cond block ELSE (block | if_stmt)
            tail = children[4]
            other = tail if isinstance(tail, list) else [tail]
        return A.If(cond, then, other, _loc(if_tok))

    def for_stmt(self, meta, children):
        for_tok, name, lo, hi, body = children
        return A.For(str(name), lo, hi, body, _loc(for_tok))

    def skip(self, meta, children):
        return A.Skip(_loc(children[0]))

    def block(self, meta, children):
        return list(children)

    # -------------------------------------------------------------- expressions
    def binop(self, meta, children):
        left, op, right = children
        return A.BinOp(str(op), left, right, _loc(op))

    def unop(self, meta, children):
        op, operand = children
        return A.UnOp(str(op), operand, _loc(op))

    def int_lit(self, meta, children):
        return A.IntLit(_int(children[0]), _loc(children[0]))

    def true_lit(self, meta, children):
        return A.IntLit(1, _loc(children[0]))

    def false_lit(self, meta, children):
        return A.IntLit(0, _loc(children[0]))

    def var(self, meta, children):
        return A.Var(str(children[0]), _loc(children[0]))

    def index(self, meta, children):
        name, idx = children
        return A.Index(str(name), idx, _loc(name))

    def select(self, meta, children):
        kw, c, a, b = children
        return A.Select(c, a, b, _loc(kw))

    def len_expr(self, meta, children):
        kw, name = children
        return A.Len(str(name), _loc(kw))


_TOKEN_NAMES = {
    "SEMICOLON": "`;`", "EQUAL": "`=`", "LPAR": "`(`", "RPAR": "`)`", "LBRACE": "`{`",
    "RBRACE": "`}`", "LSQB": "`[`", "RSQB": "`]`", "COMMA": "`,`", "__ANON_0": "`:=`",
    "__ANON_1": "`..`", "NAME": "identifier", "INT": "integer", "NUMBER": "integer", "SIGNED_NUMBER": "integer",
    "LABEL": "`public`/`secret`", "$END": "end of input",
}


def _token_name(t: str) -> str:
    if t in _TOKEN_NAMES:
        return _TOKEN_NAMES[t]
    for term in _lark().terminals:
        if term.name == t and term.pattern.type == "str":
            return f"`{term.pattern.value}`"
    return t


def parse(source: str) -> A.Program:
    """Parse CT-IMP source text into a :class:`ctcheck.ast.Program`."""
    try:
        tree = _lark().parse(source)
    except UnexpectedEOF:
        raise ParseError("unexpected end of input", A.NO_LOC) from None
    except UnexpectedToken as e:
        expected = ", ".join(sorted({_token_name(t) for t in e.expected})[:20])
        tok = "end of input" if e.token.type == "$END" else f"`{e.token}`"
        raise ParseError(
            f"unexpected {tok}; expected one of: {expected}",
            A.Loc(e.line, e.column),
        ) from None
    except UnexpectedCharacters as e:
        raise ParseError(f"unexpected character {source[e.pos_in_stream]!r}", A.Loc(e.line, e.column)) from None
    except UnexpectedInput as e:  # pragma: no cover - defensive
        raise ParseError(str(e), A.Loc(getattr(e, "line", 0), getattr(e, "column", 0))) from None
    prog = _ToAst().transform(tree)
    prog.source = source
    return prog


def parse_file(path) -> A.Program:
    return parse(Path(path).read_text())
