"""Abstract syntax for CT-IMP: IMP extended with security labels, fixed-size
arrays, bounded ``for`` loops and a branch-free ``select`` primitive."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union


class Label(Enum):
    """Two-point security lattice  PUBLIC ⊑ SECRET."""

    PUBLIC = "public"
    SECRET = "secret"

    def join(self, other: "Label") -> "Label":
        return Label.SECRET if Label.SECRET in (self, other) else Label.PUBLIC

    def flows_to(self, other: "Label") -> bool:
        return self is Label.PUBLIC or other is Label.SECRET

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Loc:
    line: int
    column: int

    def __str__(self) -> str:
        return f"{self.line}:{self.column}"


NO_LOC = Loc(0, 0)


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------


@dataclass
class IntLit:
    value: int
    loc: Loc = NO_LOC


@dataclass
class Var:
    name: str
    loc: Loc = NO_LOC


@dataclass
class Index:
    """Array read ``a[e]``."""

    array: str
    index: "Expr"
    loc: Loc = NO_LOC


@dataclass
class Len:
    """``len(a)`` -- the declared (public, static) size of an array."""

    array: str
    loc: Loc = NO_LOC


@dataclass
class BinOp:
    op: str
    left: "Expr"
    right: "Expr"
    loc: Loc = NO_LOC


@dataclass
class UnOp:
    op: str
    operand: "Expr"
    loc: Loc = NO_LOC


@dataclass
class Select:
    """``select(c, a, b)``: branch-free conditional move.

    Both ``a`` and ``b`` are always evaluated, so the condition may be secret.
    """

    cond: "Expr"
    then: "Expr"
    other: "Expr"
    loc: Loc = NO_LOC


Expr = Union[IntLit, Var, Index, Len, BinOp, UnOp, Select]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


@dataclass
class Skip:
    loc: Loc = NO_LOC


@dataclass
class Assign:
    target: str
    value: Expr
    loc: Loc = NO_LOC


@dataclass
class ArrayAssign:
    array: str
    index: Expr
    value: Expr
    loc: Loc = NO_LOC


@dataclass
class If:
    cond: Expr
    then: List["Stmt"]
    other: List["Stmt"]
    loc: Loc = NO_LOC


@dataclass
class For:
    """``for i in lo .. hi { body }`` iterates i = lo, lo+1, ..., hi-1.

    Bounds are evaluated once, on entry; ``i`` is read-only in the body.
    """

    var: str
    lo: Expr
    hi: Expr
    body: List["Stmt"]
    loc: Loc = NO_LOC


Stmt = Union[Skip, Assign, ArrayAssign, If, For]


# --------------------------------------------------------------------------
# Declarations and programs
# --------------------------------------------------------------------------


@dataclass
class ScalarDecl:
    label: Label
    name: str
    init: Optional[int] = None
    loc: Loc = NO_LOC


@dataclass
class ArrayDecl:
    label: Label
    name: str
    size: int
    init: Optional[List[int]] = None
    loc: Loc = NO_LOC


Decl = Union[ScalarDecl, ArrayDecl]


@dataclass
class Program:
    decls: List[Decl]
    body: List[Stmt]
    source: str = field(default="", repr=False)

    def scalars(self) -> List[ScalarDecl]:
        return [d for d in self.decls if isinstance(d, ScalarDecl)]

    def arrays(self) -> List[ArrayDecl]:
        return [d for d in self.decls if isinstance(d, ArrayDecl)]

    def decl(self, name: str) -> Optional[Decl]:
        for d in self.decls:
            if d.name == name:
                return d
        return None


def iter_stmts(stmts: List[Stmt]):
    """Pre-order traversal over every statement, including nested ones."""
    for s in stmts:
        yield s
        if isinstance(s, If):
            yield from iter_stmts(s.then)
            yield from iter_stmts(s.other)
        elif isinstance(s, For):
            yield from iter_stmts(s.body)

