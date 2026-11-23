"""Randomised testing of the soundness theorem on generated programs.

CT soundness: if a program is accepted in CT mode, then any two runs whose
inputs agree on public data produce identical observations (trace, cost,
public outputs).  The generator mixes well-typed and ill-typed programs, and
we check the oracle has teeth by confirming it does find leaks among
*rejected* programs.
"""

import pytest

from ctcheck import Mode, check, pretty
from ctcheck.progen import random_program
from ctcheck.relational import search_leak

N_PROGRAMS = 400


@pytest.fixture(scope="module")
def corpus():
    progs = [random_program(seed) for seed in range(N_PROGRAMS)]
    return [(p, check(p, Mode.CT), check(p, Mode.NI)) for p in progs]


def test_generator_produces_a_mix(corpus):
    accepted = sum(r.ok for _, r, _ in corpus)
    assert 0.3 * N_PROGRAMS < accepted < 0.9 * N_PROGRAMS


def test_ct_soundness_on_random_programs(corpus):
    for i, (prog, res, _) in enumerate(corpus):
        if not res.ok:
            continue
        ls = search_leak(prog, trials=25, seed=i)
        assert not ls.leaked, f"{ls.divergence}\n{pretty.program(prog)}"


def test_oracle_detects_leaks_in_rejected_programs(corpus):
    witnessed = 0
    for i, (prog, res, _) in enumerate(corpus):
        if not res.ok and search_leak(prog, trials=25, seed=i).leaked:
            witnessed += 1
    assert witnessed >= 10


def test_ct_acceptance_implies_ni_acceptance(corpus):
    """CT is strictly stronger than NI on this language."""
    for prog, ct, ni in corpus:
        if ct.ok:
            assert ni.ok, pretty.program(prog)


def test_ni_soundness_for_public_outputs(corpus):
    """NI-accepted programs keep public outputs equal -- but only when neither
    run aborts: a secret-dependent out-of-bounds abort is a termination
    channel that NI typing (unlike CT typing) does not rule out."""
    from ctcheck.interp import run
    from ctcheck.relational import sample_inputs
    import random
    from ctcheck.ast import Label

    for i, (prog, _, ni) in enumerate(corpus):
        if not ni.ok:
            continue
        rng = random.Random(i)
        for _ in range(10):
            pub = sample_inputs(prog, rng, Label.PUBLIC)
            a = run(prog, {**pub, **sample_inputs(prog, rng, Label.SECRET)}, 50_000)
            b = run(prog, {**pub, **sample_inputs(prog, rng, Label.SECRET)}, 50_000)
            if a.error or b.error:
                continue
            assert a.observation().public_out == b.observation().public_out, pretty.program(prog)
