# ctcheck — a type system for constant-time programs

Implementation of **Option 1** of the CS587 project proposal (Ravilov & Liu):
a security type checker for CT-IMP, a small extension of IMP with
public/secret labels, fixed-size arrays and bounded loops, plus an
instrumented interpreter that records the observations a timing adversary is
assumed to see.

The checker rejects any program in which secret data could influence

* **execution paths**: `if` guards must be public (`CT-BRANCH`),
* **loop counts**: `for` bounds must be public (`CT-LOOP`),
* **memory-access addresses**: array indices must be public (`CT-INDEX`),
* **public outputs**: no secret→public assignment (`EXPLICIT-FLOW`).

A classic Volpano–Smith–Irvine noninterference checker (`--mode ni`) is
included as a baseline.

## Setup

Requires Python ≥ 3.9.

```bash
uv venv .venv && uv pip install --python .venv -e '.[test]'
```

Or use plain pip: `python -m venv .venv && .venv/bin/pip install -e '.[test]'`.

## Usage

```bash
.venv/bin/ctcheck check examples/*/*.ct
```

```bash
.venv/bin/ctcheck check --mode ni examples/leaky/leak_modexp_branch.ct
```

```bash
.venv/bin/ctcheck run examples/safe/ct_cswap.ct --set swap=1 --set x=1,2,3,4,5,6,7,8 --trace
```

```bash
.venv/bin/ctcheck compare examples/leaky/leak_sbox_lookup.ct --trials 500
```

```bash
.venv/bin/ctcheck compare examples/leaky/leak_magic_value.ct --a pw=0x5eed1234 --b pw=0
```

* `check` type-checks one or more files and reports every violation with
  `line:col`, a rule code, and the secret variables responsible. It exits with
  1 if any file is rejected and 2 on a parse error. Flags: `--mode ct|ni`,
  `--vartime-div` (also require public operands for `/` and `%`), and
  `--json`.
* `run` executes a program and prints the final state, the modeled cost,
  operation counts and, with `--trace`, the observation trace. Inputs not
  given default to the declaration's initializer, or 0.
* `compare` runs the program twice with the **same public inputs and
  different secrets**, then compares the trace, the cost and the public
  outputs. With `--a/--b` it uses the given secret inputs; otherwise it runs
  random trials. It exits with 1 and prints the inputs when a leak is
  witnessed.

Example diagnostic:

```
examples/leaky/leak_public_table_value.ct: REJECTED (ct mode, 0.01 ms)
  ...:10:1: [EXPLICIT-FLOW] `out` is public but the assigned value depends on `key`
  ...:10:8: [CT-INDEX] read of `tbl[...]` uses an index that depends on `key`; the accessed address would leak it
```

## The language

```c
public int n = 4;                   // scalar, optional constant initializer
secret int key;                     // no initializer: an input
public int[8] tbl = {1, 2, 3, 4, 5, 6, 7, 8};
secret int[8] buf;

for i in 0 .. n {                   // i = 0, 1, ..., n-1; bounds evaluated once; i is read-only
  buf[i] := select(key & 1, tbl[i], -tbl[i]);   // branch-free conditional
}
if (n > 3) { skip; } else if (n == 0) { skip; } else { skip; }
```

* Declarations come first, then statements. The statements are `x := e;`,
  `a[e] := e;`, `if/else if/else`, `for`, and `skip;`.
* Expressions use C operators and precedence: `+ - * / % & | ^ << >> == != <
  <= > >= && || ! ~` and unary `-`. They also include decimal and hex
  literals, `true`/`false`, `len(a)`, and `select(c, a, b)`.
* Integers are 32-bit two's complement. All operators are total
  (`x / 0 = -1`, `x % 0 = x`), and `&&`/`||` do **not** short-circuit.
  `select` evaluates all three operands, so its condition may be secret.
* The only runtime error is an out-of-bounds index. It is recorded in the
  trace, and for well-typed CT programs it can depend only on public data.
* Comments use `//` or `/* */`.

## Observation model

The interpreter records `branch(loc, taken)`, `loop(loc, iterations)`,
`load(a, i)` and `store(a, i)` events, plus a total **modeled cost**. Every
primitive operation has a fixed cost (`COSTS` in `ctcheck/interp.py`). Two
runs are indistinguishable when their traces, costs and final public values
are all equal. `docs/soundness.md` states the theorem: well-typed ⇒
indistinguishable for any two inputs that agree on public data. It gives the
typing rules and a proof sketch, and lists what is out of scope, such as
compilation and microarchitectural timing.

## Repository layout

| path | contents |
|---|---|
| `ctcheck/grammar.lark`, `parser.py`, `ast.py` | Lark grammar, parser and AST |
| `ctcheck/typecheck.py` | CT and NI security type checkers |
| `ctcheck/interp.py` | instrumented interpreter and cost model |
| `ctcheck/relational.py` | two-run comparison and random leak search |
| `ctcheck/cli.py` | command-line interface |
| `ctcheck/progen.py`, `pretty.py` | random program generator and pretty-printer, used for fuzzing |
| `ctcheck/examples.py` | reader for example expectation headers |
| `examples/{safe,leaky,conservative}/` | 30 example programs, each with `expect-ct`, `expect-ni` and `leaks` headers |
| `tests/` | pytest suite with 231 tests |
| `eval/run_eval.py` | evaluation driver; writes `eval/results.md` and `eval/results.json` |
| `docs/soundness.md` | typing rules, soundness theorem and proof sketch |

## Tests and evaluation

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/python eval/run_eval.py
```

Current results (see `eval/results.md`):

| checker | leaky & rejected | safe & accepted | conservative rejections | leaky but accepted |
|---|---:|---:|---:|---:|
| CT mode | 12 | 13 | 5 | **0** |
| NI baseline | 5 | 16 | 2 | 7 |

* All 30 examples match their manually justified verdict and diagnostic
  codes in both modes.
* Random two-run testing witnesses 11 of the 12 leaks and never separates an
  accepted program. The twelfth leak, a comparison against a magic constant,
  is caught statically but needs hand-picked inputs to witness.
* Fuzzing 1000 random programs found 0 soundness violations among the 697
  that were accepted.
* Checking time is linear in program size: about 0.003 ms per example and
  about 20 ms for 10,000 statements.
