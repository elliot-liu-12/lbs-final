# CT-IMP: typing rules and soundness argument

This document states the execution model, the type system implemented in
`ctcheck/typecheck.py`, and the soundness property it guarantees, followed by
a proof sketch for the core rules. The guarantee concerns **this execution
model only**; compilation and processor-level timing are outside scope.

## 1. Language

```
ℓ ::= P | S                                   labels, P ⊑ S
e ::= n | x | a[e] | len(a) | e ⊕ e | ⊖ e | select(e, e, e)
c ::= skip | x := e | a[e] := e | c; c
    | if (e) { c } else { c }
    | for i in e .. e { c }
```

`⊕` ranges over `+ - * / % & | ^ << >> == != < <= > >= && ||` and `⊖` over
`- ! ~`. Declarations `ℓ int x` and `ℓ int[N] a` give a typing environment Γ
that maps every scalar and array to a label and every array to a static size.
Loop variables are read-only, scoped to the loop body, and may not shadow
another name.

## 2. Execution model

Values are 32-bit two's-complement integers. All operators are total
(`x / 0 = −1`, `x % 0 = x`); `&&` and `||` evaluate both operands;
`select(c, a, b)` evaluates all three operands and returns `a` if `c ≠ 0`,
otherwise `b`.

A memory `m` maps scalars to values and arrays to value sequences of their
declared size. Evaluation is big-step and produces an **observation** `o`, a
sequence of events, plus a modeled cost `κ`:

| event | produced by | meaning |
|---|---|---|
| `branch(ℓoc, b)` | `if` | which arm was taken |
| `loop(ℓoc, n)` | `for` | number of iterations |
| `load(a, k)` / `store(a, k)` | `a[e]` / `a[e] := e'` | address accessed |
| `error(msg)` | out-of-bounds access, step limit | abnormal termination |

Every primitive operation has a fixed cost (table `COSTS` in
`ctcheck/interp.py`), so `κ` is a function of the sequence of operations
executed. We write `⟨e, m⟩ ⇓ (v, o, κ)` and `⟨c, m⟩ ⇓ (r, o, κ)`, where the
result `r` is either a final memory or `error`.

The **adversary** observes `o`, `κ`, and the final values of public
variables and public arrays.

**Low-equivalence.** `m₁ ~Γ m₂` iff `m₁(x) = m₂(x)` for every scalar or loop
variable `x` with `Γ(x) = P`, and `m₁(a) = m₂(a)` for every array with
`Γ(a) = P`. (Array sizes are static and therefore always equal.)

## 3. Typing rules (CT mode)

Expressions, `Γ ⊢ e : ℓ`:

```
                                                     Γ ⊢ e : P
──────────── (T-CONST)   ────────────── (T-VAR)   ──────────────── (T-READ)
 Γ ⊢ n : P                Γ ⊢ x : Γ(x)             Γ ⊢ a[e] : Γ(a)

 Γ ⊢ e₁ : ℓ₁   Γ ⊢ e₂ : ℓ₂                Γ ⊢ c : ℓ₁   Γ ⊢ e₁ : ℓ₂   Γ ⊢ e₂ : ℓ₃
──────────────────────────── (T-OP)     ─────────────────────────────────────── (T-SELECT)
 Γ ⊢ e₁ ⊕ e₂ : ℓ₁ ⊔ ℓ₂                    Γ ⊢ select(c, e₁, e₂) : ℓ₁ ⊔ ℓ₂ ⊔ ℓ₃
```

(`len(a)` and unary operators are analogous to T-CONST and T-OP.)

Commands, `Γ ⊢ c`:

```
 Γ ⊢ e : ℓ    ℓ ⊑ Γ(x)                 Γ ⊢ i : P    Γ ⊢ e : ℓ    ℓ ⊑ Γ(a)
────────────────────── (T-ASSIGN)     ─────────────────────────────────── (T-AWRITE)
 Γ ⊢ x := e                             Γ ⊢ a[i] := e

 Γ ⊢ e : P    Γ ⊢ c₁    Γ ⊢ c₂          Γ ⊢ e₁ : P    Γ ⊢ e₂ : P    Γ, i : P ⊢ c
──────────────────────────────── (T-IF) ──────────────────────────────────────── (T-FOR)
 Γ ⊢ if (e) { c₁ } else { c₂ }           Γ ⊢ for i in e₁ .. e₂ { c }

 Γ ⊢ c₁    Γ ⊢ c₂
────────────────── (T-SEQ)       ──────────── (T-SKIP)
 Γ ⊢ c₁; c₂                       Γ ⊢ skip
```

The premises highlighted by the implementation's diagnostics are:
`ℓ ⊑ Γ(x)` (`EXPLICIT-FLOW`), the guard of T-IF (`CT-BRANCH`), the bounds of
T-FOR (`CT-LOOP`), and the index premises of T-READ and T-AWRITE
(`CT-INDEX`).

**No program-counter label is needed.** In Volpano–Smith–Irvine typing [1]
commands carry a `pc` label raised under secret guards, and a *confinement*
lemma shows commands typed at `pc = S` do not write public locations. In CT
mode every guard and loop bound is public, so `pc` is always `P` and both the
`pc` machinery and the confinement lemma are unnecessary. The NI baseline
(`--mode ni`) keeps them (see §6).

## 4. Soundness

> **Theorem (CT soundness).** Let `Γ ⊢ c` in CT mode and `m₁ ~Γ m₂`. If
> `⟨c, m₁⟩ ⇓ (r₁, o₁, κ₁)` and `⟨c, m₂⟩ ⇓ (r₂, o₂, κ₂)`, then
> 1. `o₁ = o₂` and `κ₁ = κ₂`, and
> 2. either `r₁ = r₂ = error` (with the same message), or `r₁, r₂` are
>    memories with `r₁ ~Γ r₂`.

In words: two runs that agree on public inputs take the same branches, run
every loop the same number of times, touch the same addresses, cost the same,
fail at the same point, and finish with the same public outputs.

**Lemma 1 (expressions).** Let `Γ ⊢ e : ℓ` and `m₁ ~Γ m₂`, with
`⟨e, mⱼ⟩ ⇓ (vⱼ, oⱼ, κⱼ)` for `j = 1, 2`. Then `o₁ = o₂`, `κ₁ = κ₂`, both
evaluations fail or both succeed, and if `ℓ = P` then `v₁ = v₂`.

*Proof.* By induction on the structure of `e`.

* `n`, `len(a)`: no events; fixed cost; the value is a constant (the
  declared size is static).
* `x`: fixed cost, no events. If `ℓ = Γ(x) = P` then `m₁(x) = m₂(x)` by
  low-equivalence.
* `a[e']`: by T-READ, `Γ ⊢ e' : P`, so by IH `e'` produces equal events, cost,
  and value `k` in both runs. Both runs then emit `load(a, k)`, charge the
  same fixed cost, and perform the same bounds check against the same static
  size, so they fail or succeed together. If `ℓ = Γ(a) = P` then
  `m₁(a) = m₂(a)`, so `m₁(a)[k] = m₂(a)[k]`.
* `e₁ ⊕ e₂`: both operands are always evaluated (no short-circuiting), so
  the observation is `o(e₁) · o(e₂)` and the cost is
  `κ(e₁) + κ(e₂) + COSTS[⊕]`; both are equal by IH. Because `⊕` is total it
  never fails by itself. If `ℓ₁ ⊔ ℓ₂ = P` then both operands are public, so
  by IH their values are equal and so is the result.
* `select(c, e₁, e₂)`: all three operands are evaluated in both runs, so
  this case is like `⊕`. Note that the guard may be secret, since the
  condition never decides *which* sub-expressions are evaluated. ∎

**Proof of the theorem.** By induction on the derivation of
`⟨c, m₁⟩ ⇓ (r₁, o₁, κ₁)`, with a case analysis on `c`.

* `skip`: trivial.
* `x := e`: by Lemma 1 the observations and costs agree and the two runs
  fail together. If `Γ(x) = S` then updating `x` preserves `~Γ`. If
  `Γ(x) = P` then T-ASSIGN gives `ℓ ⊑ P`, so `ℓ = P`, the two values are
  equal by Lemma 1, and `~Γ` is preserved.
* `a[i] := e`: T-AWRITE gives `Γ ⊢ i : P`, so the index `k` is the same in
  both runs (Lemma 1). Both emit `store(a, k)` and perform the same bounds
  check. If `Γ(a) = P` then the value is public and therefore equal, so
  `r₁(a) = r₂(a)`.
* `c₁; c₂`: by the IH for `c₁`, either both runs fail with identical
  observations, or the intermediate memories are low-equivalent. In the
  second case, apply the IH to `c₂`. Observations concatenate.
* `if (e) {c₁} else {c₂}`: T-IF gives `Γ ⊢ e : P`, so the guard has the
  same value in both runs (Lemma 1). Both emit the same `branch(ℓoc, b)`
  event and continue with the same arm, and the IH applies to that arm.
* `for i in e₁ .. e₂ {c}`: T-FOR makes both bounds public, so `lo` and `hi`
  agree, and `n = max(0, hi − lo)` and the event `loop(ℓoc, n)` agree. By an
  inner induction on the iteration number `k < n`, both runs execute the
  body with `i = lo + k`, which is the same public value, starting from
  low-equivalent memories (`i : P` in the extended environment). The outer
  IH applies to each iteration.

The interpreter's step limit counts executed statements and iterations. The
induction shows that both runs execute the same sequence of statements, so
they exhaust the limit at the same point. ∎

**Corollaries.**
*(i)* The final public state is noninterferent (part 2).
*(ii)* The modeled cost is equal (part 1). Cost is a function of the executed
operation sequence, and that sequence is the same in both runs.
*(iii)* Every CT-typable program is NI-typable: in CT mode `pc = P`, so the
NI side condition `pc ⊑ Γ(x)` holds trivially. This is checked empirically
in `tests/test_soundness_fuzz.py::test_ct_acceptance_implies_ni_acceptance`.

## 5. What the guarantee does *not* cover

* **Compilation and hardware.** A compiler may introduce branches (for
  example, by turning `select` back into a jump) or use variable-latency
  instructions. Caches, speculation and prefetching are not modeled beyond
  the address trace.
* **Division latency.** By default `/` and `%` have fixed cost, as the
  proposal specifies. `--vartime-div` adds the stricter premise that their
  operands must be public (`CT-VARTIME`). That rule only adds premises, so
  the theorem still holds.
* **Declassification.** There is no way to release a secret
  intentionally; for example, the result of `ct_compare.ct` stays secret.
* **Precision.** The system is flow-insensitive and does no arithmetic
  reasoning. It rejects programs whose observations are in fact constant,
  as the `examples/conservative/` suite shows (`key * 0`, `key ^ key`,
  `select(key, 8, 8)`, a dead guard, and a secret variable overwritten with
  a constant). CtChecker [2] recovers some of this precision with a more
  elaborate analysis.

## 6. The NI baseline and a termination channel

`--mode ni` implements the Volpano–Smith–Irvine rules [1]. Secret guards and
bounds are allowed but raise `pc`, assignments need `ℓ ⊔ pc ⊑ Γ(x)`, a
secret-indexed read has label `Γ(a) ⊔ ℓᵢ`, and a write `a[i] := e` needs
`ℓᵢ ⊔ ℓₑ ⊔ pc ⊑ Γ(a)`. This guarantees *termination-insensitive*
noninterference of the final public state only. Two observations follow from
the evaluation:

1. NI accepts 7 of the 12 leaky examples. Every one of them leaks through
   branches, loop counts or addresses, not through final values.
2. NI typing permits a secret-dependent array index, so a run can abort
   (out of bounds) depending on a secret. That abort is a termination
   channel. `tests/test_soundness_fuzz.py::test_ni_soundness_for_public_outputs`
   therefore compares only runs that both terminate normally. CT typing
   closes this channel because every index is public (Lemma 1).

## 7. How testing complements the proof

* `tests/test_examples.py` checks the 30 hand-justified examples in both
  modes. It also checks that random two-run testing never separates an
  accepted program, using 1000 random secret pairs per program.
* `tests/test_soundness_fuzz.py` generates 400 random programs, both
  well-typed and ill-typed. It checks the theorem's conclusion on every
  accepted program, and checks that the oracle has power by requiring it to
  witness leaks in rejected ones. `eval/run_eval.py` repeats this on 1000
  programs.

[1] D. Volpano, C. Irvine, G. Smith. *A Sound Type System for Secure Flow Analysis.* JCS 1996.
[2] Q. Zhou, S. Dang, D. Zhang. *CtChecker: A Precise, Sound and Efficient Static Analysis for Constant-Time Programming.* ECOOP 2024.
