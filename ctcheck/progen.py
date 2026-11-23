"""Random CT-IMP program generator used to fuzz the soundness theorem.

Programs are generated *mostly* well-typed: guards, loop bounds and indices
are drawn from public sub-expressions, and assignments respect labels.  With a
small probability each of those choices is replaced by an arbitrary
expression, so the generator also produces ill-typed programs.
"""

from __future__ import annotations

import random
from typing import List

from . import ast as A
from .ast import Label

P, S = Label.PUBLIC, Label.SECRET
BINOPS = ["+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", "==", "!=", "<", "<=", ">", ">=", "&&", "||"]
UNOPS = ["-", "!", "~"]
ARRAY_SIZE = 4


class ProgramGenerator:
    def __init__(self, rng: random.Random, mutate: float = 0.08):
        self.rng = rng
        self.mutate = mutate
        self.scalars = {"p0": P, "p1": P, "p2": P, "s0": S, "s1": S, "s2": S}
        self.arrays = {"pa": P, "sa": S}
        self.loop_vars: List[str] = []

    def decls(self) -> List[A.Decl]:
        ds: List[A.Decl] = [A.ScalarDecl(lab, n) for n, lab in self.scalars.items()]
        ds += [A.ArrayDecl(lab, n, ARRAY_SIZE) for n, lab in self.arrays.items()]
        return ds

    # ------------------------------------------------------------ expressions
    def wild(self) -> bool:
        return self.rng.random() < self.mutate

    def index(self, depth: int) -> A.Expr:
        """A (usually) public index, (usually) masked into bounds."""
        e = self.expr(depth - 1, public=not self.wild())
        if self.rng.random() < 0.9:
            e = A.BinOp("&", e, A.IntLit(ARRAY_SIZE - 1))
        return e

    def expr(self, depth: int, public: bool) -> A.Expr:
        r = self.rng
        if depth <= 0 or r.random() < 0.3:
            choices = ["lit", "var"]
        else:
            choices = ["lit", "var", "idx", "bin", "bin", "un", "sel"]
        kind = r.choice(choices)
        if kind == "lit":
            return A.IntLit(r.choice([0, 1, 2, 3, 7, -1, 255, 1 << 20]))
        if kind == "var":
            names = [n for n, l in self.scalars.items() if not public or l is P] + self.loop_vars
            return A.Var(r.choice(names))
        if kind == "idx":
            arrs = [n for n, l in self.arrays.items() if not public or l is P]
            return A.Index(r.choice(arrs), self.index(depth))
        if kind == "bin":
            return A.BinOp(r.choice(BINOPS), self.expr(depth - 1, public), self.expr(depth - 1, public))
        if kind == "un":
            return A.UnOp(r.choice(UNOPS), self.expr(depth - 1, public))
        return A.Select(self.expr(depth - 1, public), self.expr(depth - 1, public), self.expr(depth - 1, public))

    # --------------------------------------------------------------- commands
    def stmt(self, depth: int) -> A.Stmt:
        r = self.rng
        kinds = ["asn", "asn", "asn", "awr", "skip"]
        if depth > 0:
            kinds += ["if", "if", "for"]
        kind = r.choice(kinds)
        if kind == "skip":
            return A.Skip()
        if kind == "asn":
            target = r.choice(list(self.scalars))
            public = self.scalars[target] is P and not self.wild()
            return A.Assign(target, self.expr(3, public))
        if kind == "awr":
            arr = r.choice(list(self.arrays))
            public = self.arrays[arr] is P and not self.wild()
            return A.ArrayAssign(arr, self.index(2), self.expr(3, public))
        if kind == "if":
            cond = self.expr(2, public=not self.wild())
            return A.If(cond, self.block(depth - 1), self.block(depth - 1) if r.random() < 0.6 else [])
        var = f"i{len(self.loop_vars)}"
        lo = self.expr(1, public=not self.wild())
        hi = A.BinOp("&", self.expr(2, public=not self.wild()), A.IntLit(3))
        self.loop_vars.append(var)
        body = self.block(depth - 1)
        self.loop_vars.pop()
        return A.For(var, A.BinOp("&", lo, A.IntLit(3)), hi, body)

    def block(self, depth: int) -> List[A.Stmt]:
        return [self.stmt(depth) for _ in range(self.rng.randint(1, 3))]

    def program(self) -> A.Program:
        return A.Program(self.decls(), [self.stmt(2) for _ in range(self.rng.randint(2, 6))])


def random_program(seed: int, mutate: float = 0.08) -> A.Program:
    return ProgramGenerator(random.Random(seed), mutate).program()
