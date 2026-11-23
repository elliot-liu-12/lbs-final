"""Command-line interface: ``ctcheck {check,run,compare} ...``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Dict, List

from . import ast as A
from .interp import run
from .parser import ParseError, parse_file
from .relational import _ev, compare, search_leak
from .typecheck import Mode, check


def _parse_assignments(items: List[str]) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"error: expected NAME=VALUE, got {item!r}")
        name, raw = item.split("=", 1)
        raw = raw.strip().strip("[]{}")
        if "," in raw:
            out[name.strip()] = [int(x, 0) for x in raw.split(",") if x.strip()]
        else:
            out[name.strip()] = int(raw, 0)
    return out


def _load(path: str) -> A.Program:
    try:
        return parse_file(path)
    except ParseError as e:
        print(f"{path}:{e}", file=sys.stderr)
        raise SystemExit(2)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(2)


def cmd_check(args) -> int:
    mode = Mode(args.mode)
    status = 0
    reports = []
    for path in args.files:
        try:
            prog = parse_file(path)
        except (ParseError, OSError) as e:
            print(f"{path}:{e}", file=sys.stderr)
            status = 2
            continue
        t0 = time.perf_counter()
        res = check(prog, mode, variable_time_div=args.vartime_div)
        elapsed = (time.perf_counter() - t0) * 1000
        if not res.ok:
            status = max(status, 1)
        if args.json:
            reports.append(
                {
                    "file": path,
                    "mode": mode.value,
                    "ok": res.ok,
                    "time_ms": round(elapsed, 3),
                    "diagnostics": [
                        {"code": d.code, "line": d.loc.line, "column": d.loc.column, "message": d.message,
                         "sources": list(d.sources)}
                        for d in res.diagnostics
                    ],
                }
            )
            continue
        verdict = "ACCEPTED" if res.ok else "REJECTED"
        print(f"{path}: {verdict} ({mode.value} mode, {elapsed:.2f} ms)")
        for d in res.diagnostics:
            print(f"  {path}:{d}")
    if args.json:
        json.dump(reports, sys.stdout, indent=2)
        print()
    return status


def cmd_run(args) -> int:
    prog = _load(args.file)
    try:
        res = run(prog, _parse_assignments(args.set), args.max_steps)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    labels = {d.name: d.label.value for d in prog.decls}
    print("final state:")
    for n, v in res.scalars.items():
        print(f"  {labels[n]:6} {n} = {v}")
    for n, v in res.arrays.items():
        print(f"  {labels[n]:6} {n} = {v}")
    print(f"modeled cost: {res.cost}")
    print("operation counts: " + ", ".join(f"{k}={v}" for k, v in sorted(res.op_counts.items())))
    if args.trace:
        print(f"trace ({len(res.trace)} events):")
        for ev in res.trace:
            print(f"  {_ev(ev)}")
    else:
        print(f"trace: {len(res.trace)} events (use --trace to print)")
    if res.error:
        print(f"runtime error: {res.error}")
        return 3
    return 0


def cmd_compare(args) -> int:
    prog = _load(args.file)
    if args.a is not None or args.b is not None:
        if args.a is None or args.b is None:
            print("error: --a and --b must be given together", file=sys.stderr)
            return 2
        d = compare(prog, _parse_assignments(args.public), _parse_assignments(args.a),
                    _parse_assignments(args.b), args.max_steps)
        trials = 1
    else:
        ls = search_leak(prog, args.trials, args.seed, _parse_assignments(args.public), args.max_steps)
        d, trials = ls.divergence, ls.trials
    if d is None:
        print(f"{args.file}: no divergence in {trials} trial(s)")
        return 0
    print(f"{args.file}: LEAK WITNESSED after {trials} trial(s)")
    print(f"  {d.kind}: {d.detail}")
    print(f"  run A inputs: {d.inputs_a}")
    print(f"  run B inputs: {d.inputs_b}")
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ctcheck", description="Constant-time security type checker for CT-IMP.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="type-check programs")
    pc.add_argument("files", nargs="+")
    pc.add_argument("--mode", choices=[m.value for m in Mode], default="ct",
                    help="ct: constant-time discipline (default); ni: Volpano-style noninterference only")
    pc.add_argument("--vartime-div", action="store_true",
                    help="treat / and %% as variable-latency (operands must be public)")
    pc.add_argument("--json", action="store_true", help="machine-readable output")
    pc.set_defaults(fn=cmd_check)

    pr = sub.add_parser("run", help="run a program in the instrumented interpreter")
    pr.add_argument("file")
    pr.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="input value; arrays as comma-separated lists (repeatable)")
    pr.add_argument("--trace", action="store_true", help="print the full observation trace")
    pr.add_argument("--max-steps", type=int, default=1_000_000)
    pr.set_defaults(fn=cmd_run)

    pm = sub.add_parser("compare", help="two-run test: same public inputs, different secrets")
    pm.add_argument("file")
    pm.add_argument("--public", action="append", metavar="NAME=VALUE", help="fix a public input")
    pm.add_argument("--a", action="append", metavar="NAME=VALUE", help="secret inputs of run A")
    pm.add_argument("--b", action="append", metavar="NAME=VALUE", help="secret inputs of run B")
    pm.add_argument("--trials", type=int, default=200, help="random trials when --a/--b are not given")
    pm.add_argument("--seed", type=int, default=0)
    pm.add_argument("--max-steps", type=int, default=100_000)
    pm.set_defaults(fn=cmd_compare)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
