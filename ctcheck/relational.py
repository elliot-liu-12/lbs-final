"""Two-run (relational) testing of the constant-time property.

Runs a program twice with identical public inputs and different secret inputs
and compares the observations.  A difference is a concrete *witness* of a
leak; the absence of differences over many trials is evidence (not proof)
that the program is constant-time.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from . import ast as A
from .ast import Label
from .interp import Observation, run

Value = Union[int, List[int]]


@dataclass
class Divergence:
    kind: str  # "trace" | "cost" | "public-output"
    detail: str
    inputs_a: Dict[str, Value]
    inputs_b: Dict[str, Value]
    trial: int

    def __str__(self) -> str:
        return f"{self.kind} divergence (trial {self.trial}): {self.detail}"


def _sample_scalar(rng: random.Random, label: Label) -> int:
    if label is Label.PUBLIC:
        return rng.randrange(0, 16)
    r = rng.random()
    if r < 0.15:
        return rng.choice((0, 1, -1))
    if r < 0.5:
        return rng.randrange(0, 16)
    if r < 0.75:
        return rng.randrange(-4, 64)
    return rng.randrange(-(1 << 31), 1 << 31)


def sample_inputs(
    prog: A.Program,
    rng: random.Random,
    label: Label,
    fixed: Optional[Dict[str, Value]] = None,
) -> Dict[str, Value]:
    """Sample a value for every *input* of ``label`` (declarations without an
    initializer), honouring explicitly ``fixed`` values."""
    fixed = fixed or {}
    out: Dict[str, Value] = {}
    for d in prog.decls:
        if d.label is not label:
            continue
        if d.name in fixed:
            out[d.name] = fixed[d.name]
            continue
        if d.init is not None:
            continue
        if isinstance(d, A.ScalarDecl):
            out[d.name] = _sample_scalar(rng, label)
        else:
            out[d.name] = [_sample_scalar(rng, label) for _ in range(d.size)]
    return out


def diff_observations(a: Observation, b: Observation) -> Optional[tuple]:
    """Return ``(kind, detail)`` describing the first difference, or None."""
    if a.trace != b.trace:
        for k, (x, y) in enumerate(zip(a.trace, b.trace)):
            if x != y:
                return "trace", f"event #{k}: {_ev(x)}  vs  {_ev(y)}"
        k = min(len(a.trace), len(b.trace))
        return "trace", f"trace lengths differ ({len(a.trace)} vs {len(b.trace)}) after event #{k}"
    if a.cost != b.cost:
        return "cost", f"modeled cost {a.cost} vs {b.cost}"
    if a.public_out != b.public_out:
        for (n, x), (_, y) in zip(a.public_out, b.public_out):
            if x != y:
                return "public-output", f"public `{n}` = {x} vs {y}"
    return None


def _ev(e: tuple) -> str:
    kind = e[0]
    if kind == "branch":
        return f"branch@{e[1]}:{e[2]} {'then' if e[3] else 'else'}"
    if kind == "loop":
        return f"loop@{e[1]}:{e[2]} x{e[3]}"
    if kind in ("load", "store"):
        return f"{kind} {e[1]}[{e[2]}]"
    return f"{kind}: {e[1]}"


def compare(
    prog: A.Program,
    public: Dict[str, Value],
    secret_a: Dict[str, Value],
    secret_b: Dict[str, Value],
    max_steps: int = 1_000_000,
    trial: int = 0,
) -> Optional[Divergence]:
    """Run ``prog`` on (public, secret_a) and (public, secret_b)."""
    ia = {**public, **secret_a}
    ib = {**public, **secret_b}
    oa = run(prog, ia, max_steps).observation()
    ob = run(prog, ib, max_steps).observation()
    d = diff_observations(oa, ob)
    if d is None:
        return None
    return Divergence(d[0], d[1], ia, ib, trial)


@dataclass
class LeakSearch:
    trials: int
    divergence: Optional[Divergence]

    @property
    def leaked(self) -> bool:
        return self.divergence is not None


def search_leak(
    prog: A.Program,
    trials: int = 200,
    seed: int = 0,
    fixed_public: Optional[Dict[str, Value]] = None,
    max_steps: int = 100_000,
) -> LeakSearch:
    """Randomised two-run search for an observable difference."""
    rng = random.Random(seed)
    for t in range(trials):
        pub = sample_inputs(prog, rng, Label.PUBLIC, fixed_public)
        sa = sample_inputs(prog, rng, Label.SECRET)
        sb = sample_inputs(prog, rng, Label.SECRET)
        d = compare(prog, pub, sa, sb, max_steps, trial=t)
        if d is not None:
            return LeakSearch(t + 1, d)
    return LeakSearch(trials, None)
