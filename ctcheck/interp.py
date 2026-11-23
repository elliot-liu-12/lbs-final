"""Instrumented interpreter for CT-IMP.

The interpreter executes a program and records what a constant-time adversary
is assumed to observe:

* every control-flow decision (``branch`` events, with the outcome),
* every loop's iteration count (``loop`` events),
* every array access address (``load``/``store`` events: array name + index),
* the total modeled cost, where every primitive operation has a fixed cost
  (see :data:`COSTS`),
* the final values of PUBLIC variables and arrays.

Integers are 32-bit two's complement.  Every operation is total so that
evaluation never fails on secret data: ``x / 0 == -1`` and ``x % 0 == x``
(RISC-V semantics).  ``&&``/``||`` are not short-circuit.  The only runtime
error is an out-of-bounds array access, which is recorded as an ``error``
event; well-typed CT programs can only fail this way on *public* indices.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import ast as A
from .ast import Label

MASK = 0xFFFFFFFF


def wrap(v: int) -> int:
    v &= MASK
    return v - (1 << 32) if v & 0x80000000 else v


# Fixed modeled cost of each primitive operation.
COSTS: Dict[str, int] = {
    "const": 0,
    "var": 1,
    "len": 0,
    "load": 4,
    "store": 4,
    "assign": 1,
    "branch": 2,
    "loop": 2,  # loop entry
    "iter": 2,  # per-iteration compare + increment
    "select": 3,
    "+": 1, "-": 1, "*": 3, "/": 20, "%": 20,
    "&": 1, "|": 1, "^": 1, "<<": 1, ">>": 1,
    "==": 1, "!=": 1, "<": 1, "<=": 1, ">": 1, ">=": 1,
    "&&": 1, "||": 1,
    "neg": 1, "!": 1, "~": 1,
}

Event = Tuple  # ("branch", line, col, taken) | ("loop", line, col, n) | ("load", a, i) | ...


class _Abort(Exception):
    def __init__(self, event: Event):
        self.event = event


@dataclass
class Observation:
    """Everything the constant-time adversary sees from one run."""

    trace: Tuple[Event, ...]
    cost: int
    public_out: Tuple[Tuple[str, object], ...]


@dataclass
class RunResult:
    scalars: Dict[str, int]
    arrays: Dict[str, List[int]]
    trace: List[Event]
    cost: int
    op_counts: Counter
    error: Optional[str] = None
    public_names: Tuple[str, ...] = field(default=(), repr=False)

    def observation(self) -> Observation:
        out = []
        for n in self.public_names:
            if n in self.scalars:
                out.append((n, self.scalars[n]))
            else:
                out.append((n, tuple(self.arrays[n])))
        return Observation(tuple(self.trace), self.cost, tuple(out))


Inputs = Mapping[str, Union[int, Sequence[int]]]


class Interpreter:
    def __init__(self, prog: A.Program, inputs: Optional[Inputs] = None, max_steps: int = 1_000_000):
        self.prog = prog
        self.max_steps = max_steps
        self.steps = 0
        self.trace: List[Event] = []
        self.cost = 0
        self.ops: Counter = Counter()
        self.scalars: Dict[str, int] = {}
        self.arrays: Dict[str, List[int]] = {}
        self.loop_env: List[Tuple[str, int]] = []
        inputs = dict(inputs or {})
        for d in prog.decls:
            if isinstance(d, A.ScalarDecl):
                v = inputs.pop(d.name, d.init if d.init is not None else 0)
                if not isinstance(v, int):
                    raise ValueError(f"input for scalar `{d.name}` must be an integer")
                self.scalars[d.name] = wrap(v)
            else:
                v = inputs.pop(d.name, d.init if d.init is not None else [0] * d.size)
                if isinstance(v, int):
                    v = [v] * d.size
                v = list(v)
                if len(v) != d.size:
                    raise ValueError(f"input for array `{d.name}` must have {d.size} elements, got {len(v)}")
                self.arrays[d.name] = [wrap(x) for x in v]
        if inputs:
            raise ValueError(f"unknown input(s): {', '.join(sorted(inputs))}")

    # ---------------------------------------------------------------- helpers
    def charge(self, op: str):
        self.cost += COSTS[op]
        self.ops[op] += 1

    def lookup(self, name: str) -> int:
        for n, v in reversed(self.loop_env):
            if n == name:
                return v
        return self.scalars[name]

    def address(self, kind: str, array: str, idx: int, loc: A.Loc):
        self.trace.append((kind, array, idx))
        if not 0 <= idx < len(self.arrays[array]):
            raise _Abort(("error", f"{loc}: index {idx} out of bounds for `{array}` (size {len(self.arrays[array])})"))

    # ------------------------------------------------------------ expressions
    def eval(self, e: A.Expr) -> int:
        if isinstance(e, A.IntLit):
            self.charge("const")
            return wrap(e.value)
        if isinstance(e, A.Var):
            self.charge("var")
            return self.lookup(e.name)
        if isinstance(e, A.Len):
            self.charge("len")
            return len(self.arrays[e.array])
        if isinstance(e, A.Index):
            i = self.eval(e.index)
            self.charge("load")
            self.address("load", e.array, i, e.loc)
            return self.arrays[e.array][i]
        if isinstance(e, A.UnOp):
            v = self.eval(e.operand)
            if e.op == "-":
                self.charge("neg")
                return wrap(-v)
            self.charge(e.op)
            return int(v == 0) if e.op == "!" else wrap(~v)
        if isinstance(e, A.BinOp):
            a = self.eval(e.left)
            b = self.eval(e.right)  # both operands always evaluated
            self.charge(e.op)
            return binop(e.op, a, b)
        if isinstance(e, A.Select):
            c = self.eval(e.cond)
            x = self.eval(e.then)
            y = self.eval(e.other)  # both arms always evaluated
            self.charge("select")
            return x if c != 0 else y
        raise TypeError(f"unknown expression {e!r}")  # pragma: no cover

    # --------------------------------------------------------------- commands
    def tick(self):
        self.steps += 1
        if self.steps > self.max_steps:
            raise _Abort(("error", f"step limit of {self.max_steps} exceeded"))

    def exec_block(self, stmts: List[A.Stmt]):
        for s in stmts:
            self.exec(s)

    def exec(self, s: A.Stmt):
        self.tick()
        if isinstance(s, A.Skip):
            return
        if isinstance(s, A.Assign):
            self.scalars[s.target] = self.eval(s.value)
            self.charge("assign")
            return
        if isinstance(s, A.ArrayAssign):
            i = self.eval(s.index)
            v = self.eval(s.value)
            self.charge("store")
            self.address("store", s.array, i, s.loc)
            self.arrays[s.array][i] = v
            return
        if isinstance(s, A.If):
            c = self.eval(s.cond)
            self.charge("branch")
            taken = c != 0
            self.trace.append(("branch", s.loc.line, s.loc.column, taken))
            self.exec_block(s.then if taken else s.other)
            return
        if isinstance(s, A.For):
            lo = self.eval(s.lo)
            hi = self.eval(s.hi)
            self.charge("loop")
            n = max(0, hi - lo)
            self.trace.append(("loop", s.loc.line, s.loc.column, n))
            for k in range(n):
                self.tick()
                self.charge("iter")
                self.loop_env.append((s.var, wrap(lo + k)))
                try:
                    self.exec_block(s.body)
                finally:
                    self.loop_env.pop()
            return
        raise TypeError(f"unknown statement {s!r}")  # pragma: no cover

    def run(self) -> RunResult:
        error = None
        try:
            self.exec_block(self.prog.body)
        except _Abort as ab:
            self.trace.append(ab.event)
            error = ab.event[1]
        public = tuple(d.name for d in self.prog.decls if d.label is Label.PUBLIC)
        return RunResult(self.scalars, self.arrays, self.trace, self.cost, self.ops, error, public)


def binop(op: str, a: int, b: int) -> int:
    if op == "+":
        return wrap(a + b)
    if op == "-":
        return wrap(a - b)
    if op == "*":
        return wrap(a * b)
    if op == "/":
        if b == 0:
            return -1
        q = abs(a) // abs(b)
        return wrap(q if (a >= 0) == (b >= 0) else -q)
    if op == "%":
        if b == 0:
            return a
        r = abs(a) % abs(b)
        return wrap(r if a >= 0 else -r)
    if op == "&":
        return wrap(a & b)
    if op == "|":
        return wrap(a | b)
    if op == "^":
        return wrap(a ^ b)
    if op == "<<":
        return wrap(a << (b & 31))
    if op == ">>":
        return wrap(a >> (b & 31))
    if op == "==":
        return int(a == b)
    if op == "!=":
        return int(a != b)
    if op == "<":
        return int(a < b)
    if op == "<=":
        return int(a <= b)
    if op == ">":
        return int(a > b)
    if op == ">=":
        return int(a >= b)
    if op == "&&":
        return int(a != 0 and b != 0)
    if op == "||":
        return int(a != 0 or b != 0)
    raise ValueError(f"unknown operator {op}")  # pragma: no cover


def run(prog: A.Program, inputs: Optional[Inputs] = None, max_steps: int = 1_000_000) -> RunResult:
    """Execute ``prog`` on ``inputs`` (name → int or list of ints)."""
    return Interpreter(prog, inputs, max_steps).run()
