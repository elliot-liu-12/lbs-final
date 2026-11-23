"""The example suite: checker verdicts vs. manually justified expectations,
and checker verdicts vs. dynamic two-run testing."""

import pytest

from ctcheck import Mode, check, parse
from ctcheck.examples import all_examples
from ctcheck.relational import compare, search_leak

EXAMPLES = all_examples()
ids = [e.name for e in EXAMPLES]


def test_suite_size_and_balance():
    assert 20 <= len(EXAMPLES) <= 30
    cats = {e.category for e in EXAMPLES}
    assert cats == {"safe", "leaky", "conservative"}
    for e in EXAMPLES:
        assert e.leaks == (e.category == "leaky")
        assert e.ct_accept == (e.category == "safe")


@pytest.mark.parametrize("ex", EXAMPLES, ids=ids)
def test_ct_verdict(ex):
    res = check(parse(ex.path.read_text()), Mode.CT)
    assert res.ok == ex.ct_accept
    assert set(res.codes) == ex.ct_codes


@pytest.mark.parametrize("ex", EXAMPLES, ids=ids)
def test_ni_verdict(ex):
    res = check(parse(ex.path.read_text()), Mode.NI)
    assert res.ok == ex.ni_accept
    assert set(res.codes) == ex.ni_codes


@pytest.mark.parametrize("ex", EXAMPLES, ids=ids)
def test_dynamic_agrees_with_ground_truth(ex):
    prog = parse(ex.path.read_text())
    if ex.witness is not None:
        assert compare(prog, {}, *ex.witness) is not None
        return
    found = search_leak(prog, trials=300, seed=1)
    assert found.leaked == ex.leaks, found.divergence


@pytest.mark.parametrize("ex", [e for e in EXAMPLES if e.ct_accept], ids=lambda e: e.name)
def test_accepted_programs_have_equal_observations(ex):
    """Soundness, tested: accepted ⇒ no divergence over many random pairs."""
    prog = parse(ex.path.read_text())
    assert not search_leak(prog, trials=1000, seed=7).leaked
