"""Security type checker for CT-IMP.

Two disciplines are implemented over the lattice PUBLIC ⊑ SECRET:

* ``Mode.CT`` (default) -- the constant-time discipline.  In addition to
  forbidding explicit secret→public flows, every branch guard, loop bound and
  array index must be PUBLIC.  Because no guard is ever secret, the program
  counter label is always PUBLIC and implicit flows are impossible by
  construction.  Well-typed programs produce identical observation traces
  (control-flow decisions, memory addresses, modeled cost) and identical
  public outputs for any two inputs that agree on public data.

* ``Mode.NI`` -- the classic Volpano–Smith–Irvine discipline, kept as a
  baseline.  Secret guards are allowed, but raise the program-counter label so
  that public variables cannot be assigned under them (no implicit flows).  It
  guarantees (termination-insensitive) noninterference of the final public
  state only; it says nothing about timing or address traces.

Typing rules (CT mode; ``Γ ⊢ e : ℓ`` reads "e has label ℓ"):

    Γ ⊢ n : P        Γ ⊢ x : Γ(x)        Γ ⊢ len(a) : P

    Γ ⊢ e : P                                   Γ ⊢ e1 : ℓ1   Γ ⊢ e2 : ℓ2
    ─────────────────── (T-READ)                ───────────────────────── (T-OP)
    Γ ⊢ a[e] : Γ(a)                             Γ ⊢ e1 op e2 : ℓ1 ⊔ ℓ2

    Γ ⊢ c : ℓ1  Γ ⊢ e1 : ℓ2  Γ ⊢ e2 : ℓ3
    ──────────────────────────────────── (T-SELECT)
    Γ ⊢ select(c, e1, e2) : ℓ1 ⊔ ℓ2 ⊔ ℓ3

    Γ ⊢ e : ℓ   ℓ ⊑ Γ(x)          Γ ⊢ i : P   Γ ⊢ e : ℓ   ℓ ⊑ Γ(a)
    ───────────────────── (T-ASN)  ─────────────────────────────────── (T-AWRITE)
    Γ ⊢ x := e                      Γ ⊢ a[i] := e

    Γ ⊢ e : P   Γ ⊢ c1   Γ ⊢ c2        Γ ⊢ lo : P   Γ ⊢ hi : P   Γ, i:P ⊢ c
    ────────────────────────── (T-IF)  ──────────────────────────────────── (T-FOR)
    Γ ⊢ if (e) c1 else c2              Γ ⊢ for i in lo .. hi c

The checker reports *all* violations rather than stopping at the first, and
each diagnostic names the secret sources responsible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

from . import ast as A
from .ast import Label

P = Label.PUBLIC
S = Label.SECRET


class Mode(Enum):
    CT = "ct"
    NI = "ni"


VARIABLE_TIME_OPS = frozenset({"/", "%"})


@dataclass
class Diagnostic:
    code: str
    message: str
    loc: A.Loc
    sources: Tuple[str, ...] = ()

    def __str__(self) -> str:
        where = f"{self.loc.line}:{self.loc.column}" if self.loc != A.NO_LOC else "?"
        return f"{where}: [{self.code}] {self.message}"


@dataclass
class CheckResult:
    mode: Mode
    diagnostics: List[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    @property
    def codes(self) -> List[str]:
        return sorted({d.code for d in self.diagnostics})


# The type of an expression: its label plus the secret names it depends on
# (used only for diagnostics).
Typ = Tuple[Label, FrozenSet[str]]
PUB: Typ = (P, frozenset())


def _join(*ts: Typ) -> Typ:
    lab = P
    src: FrozenSet[str] = frozenset()
    for l, s in ts:
        lab = lab.join(l)
        src = src | s
    return lab, src


def _fmt(sources: FrozenSet[str]) -> str:
    names = sorted(sources)
    return ", ".join(f"`{n}`" for n in names) if names else "secret data"


class _Checker:
    def __init__(self, prog: A.Program, mode: Mode, variable_time_div: bool):
        self.prog = prog
        self.mode = mode
        self.variable_time_div = variable_time_div
        self.diags: List[Diagnostic] = []
        self.scalars: Dict[str, Label] = {}
        self.arrays: Dict[str, Tuple[Label, int]] = {}
        # Stack of (loop variable, label).  Loop variables are read-only.
        self.loop_vars: List[Tuple[str, Label]] = []

    # ------------------------------------------------------------------ utils
    def err(self, code: str, msg: str, loc: A.Loc, sources: FrozenSet[str] = frozenset()):
        self.diags.append(Diagnostic(code, msg, loc, tuple(sorted(sources))))

    def loop_var(self, name: str) -> Optional[Label]:
        for n, lab in reversed(self.loop_vars):
            if n == name:
                return lab
        return None

    # ------------------------------------------------------------ declarations
    def declare(self):
        for d in self.prog.decls:
            if d.name in self.scalars or d.name in self.arrays:
                self.err("DUP-DECL", f"`{d.name}` is declared more than once", d.loc)
                continue
            if isinstance(d, A.ScalarDecl):
                self.scalars[d.name] = d.label
            else:
                if d.size <= 0:
                    self.err("ARRAY-SIZE", f"array `{d.name}` must have positive size", d.loc)
                if d.init is not None and len(d.init) != d.size:
                    self.err(
                        "ARRAY-INIT",
                        f"array `{d.name}` has size {d.size} but {len(d.init)} initializers",
                        d.loc,
                    )
                self.arrays[d.name] = (d.label, d.size)

    # ------------------------------------------------------------- expressions
    def expr(self, e: A.Expr) -> Typ:
        if isinstance(e, A.IntLit):
            return PUB
        if isinstance(e, A.Var):
            lv = self.loop_var(e.name)
            if lv is not None:
                return (lv, frozenset({e.name}) if lv is S else frozenset())
            if e.name in self.scalars:
                lab = self.scalars[e.name]
                return (lab, frozenset({e.name}) if lab is S else frozenset())
            if e.name in self.arrays:
                self.err("KIND", f"array `{e.name}` used as a scalar", e.loc)
            else:
                self.err("UNDECLARED", f"variable `{e.name}` is not declared", e.loc)
            return PUB
        if isinstance(e, A.Len):
            if e.array not in self.arrays:
                self.err("UNDECLARED", f"array `{e.array}` is not declared", e.loc)
            return PUB
        if isinstance(e, A.Index):
            it = self.expr(e.index)
            if e.array not in self.arrays:
                kind = "scalar" if e.array in self.scalars or self.loop_var(e.array) else None
                if kind:
                    self.err("KIND", f"scalar `{e.array}` indexed as an array", e.loc)
                else:
                    self.err("UNDECLARED", f"array `{e.array}` is not declared", e.loc)
                return it
            alab, _ = self.arrays[e.array]
            elem: Typ = (alab, frozenset({e.array}) if alab is S else frozenset())
            if it[0] is S:
                if self.mode is Mode.CT:
                    self.err(
                        "CT-INDEX",
                        f"read of `{e.array}[...]` uses an index that depends on {_fmt(it[1])}; "
                        "the accessed address would leak it",
                        e.loc,
                        it[1],
                    )
                # The value read reveals information about the index.
                return _join(elem, it)
            return elem
        if isinstance(e, A.BinOp):
            lt, rt = self.expr(e.left), self.expr(e.right)
            t = _join(lt, rt)
            if self.variable_time_div and e.op in VARIABLE_TIME_OPS and t[0] is S and self.mode is Mode.CT:
                self.err(
                    "CT-VARTIME",
                    f"operator `{e.op}` has data-dependent latency but its operands depend on {_fmt(t[1])}",
                    e.loc,
                    t[1],
                )
            return t
        if isinstance(e, A.UnOp):
            return self.expr(e.operand)
        if isinstance(e, A.Select):
            return _join(self.expr(e.cond), self.expr(e.then), self.expr(e.other))
        raise TypeError(f"unknown expression {e!r}")  # pragma: no cover

    # ---------------------------------------------------------------- commands
    def block(self, stmts: List[A.Stmt], pc: Label):
        for s in stmts:
            self.stmt(s, pc)

    def flow(self, t: Typ, pc: Label, target_label: Label, what: str, loc: A.Loc):
        """Check ``t ⊔ pc ⊑ target_label`` and explain violations."""
        if not t[0].flows_to(target_label):
            self.err(
                "EXPLICIT-FLOW",
                f"{what} is public but the assigned value depends on {_fmt(t[1])}",
                loc,
                t[1],
            )
        elif not pc.flows_to(target_label):
            self.err(
                "IMPLICIT-FLOW",
                f"{what} is public but is assigned under a secret branch or loop",
                loc,
            )

    def stmt(self, s: A.Stmt, pc: Label):
        if isinstance(s, A.Skip):
            return
        if isinstance(s, A.Assign):
            t = self.expr(s.value)
            if self.loop_var(s.target) is not None:
                self.err("LOOPVAR-ASSIGN", f"loop variable `{s.target}` is read-only", s.loc)
                return
            if s.target not in self.scalars:
                if s.target in self.arrays:
                    self.err("KIND", f"cannot assign to array `{s.target}` as a whole", s.loc)
                else:
                    self.err("UNDECLARED", f"variable `{s.target}` is not declared", s.loc)
                return
            self.flow(t, pc, self.scalars[s.target], f"`{s.target}`", s.loc)
            return
        if isinstance(s, A.ArrayAssign):
            it = self.expr(s.index)
            vt = self.expr(s.value)
            if s.array not in self.arrays:
                if s.array in self.scalars or self.loop_var(s.array) is not None:
                    self.err("KIND", f"scalar `{s.array}` indexed as an array", s.loc)
                else:
                    self.err("UNDECLARED", f"array `{s.array}` is not declared", s.loc)
                return
            alab, _ = self.arrays[s.array]
            if it[0] is S and self.mode is Mode.CT:
                self.err(
                    "CT-INDEX",
                    f"write to `{s.array}[...]` uses an index that depends on {_fmt(it[1])}; "
                    "the accessed address would leak it",
                    s.loc,
                    it[1],
                )
                self.flow(vt, pc, alab, f"array `{s.array}`", s.loc)
            else:
                # In NI mode the written location reveals the index.
                self.flow(_join(vt, it), pc, alab, f"array `{s.array}`", s.loc)
            return
        if isinstance(s, A.If):
            ct = self.expr(s.cond)
            inner = pc
            if ct[0] is S:
                if self.mode is Mode.CT:
                    self.err(
                        "CT-BRANCH",
                        f"`if` guard depends on {_fmt(ct[1])}; the branch taken would leak it "
                        "(consider `select(c, a, b)`)",
                        s.loc,
                        ct[1],
                    )
                else:
                    inner = S
            self.block(s.then, inner)
            self.block(s.other, inner)
            return
        if isinstance(s, A.For):
            bt = _join(self.expr(s.lo), self.expr(s.hi))
            inner = pc
            if bt[0] is S:
                if self.mode is Mode.CT:
                    self.err(
                        "CT-LOOP",
                        f"`for` bound depends on {_fmt(bt[1])}; the iteration count would leak it",
                        s.loc,
                        bt[1],
                    )
                else:
                    inner = S
            if s.var in self.scalars or s.var in self.arrays or self.loop_var(s.var) is not None:
                self.err("LOOPVAR-SHADOW", f"loop variable `{s.var}` shadows an existing name", s.loc)
            ivar = P if self.mode is Mode.CT else bt[0].join(pc)
            self.loop_vars.append((s.var, ivar))
            self.block(s.body, inner)
            self.loop_vars.pop()
            return
        raise TypeError(f"unknown statement {s!r}")  # pragma: no cover


def check(prog: A.Program, mode: Mode = Mode.CT, variable_time_div: bool = False) -> CheckResult:
    """Type-check ``prog`` and return every diagnostic found.

    ``variable_time_div`` additionally treats ``/`` and ``%`` as variable-latency
    instructions whose operands must be public (CT mode only).
    """
    c = _Checker(prog, mode, variable_time_div)
    c.declare()
    c.block(prog.body, P)
    c.diags.sort(key=lambda d: (d.loc.line, d.loc.column))
    return CheckResult(mode, c.diags)
