import pytest

from ctcheck import parse, run
from ctcheck.interp import COSTS, binop, wrap


def ev(expr, **inputs):
    decls = "".join(f"public int {n};" for n in inputs)
    res = run(parse(decls + f"public int r; r := {expr};"), inputs)
    return res.scalars["r"]


@pytest.mark.parametrize(
    "expr,value",
    [
        ("2147483647 + 1", -(2**31)),
        ("0 - 2147483647 - 2", 2**31 - 1),
        ("65536 * 65536", 0),
        ("7 / 2", 3),
        ("-7 / 2", -3),
        ("7 % -3", 1),
        ("-7 % 3", -1),
        ("5 / 0", -1),
        ("5 % 0", 5),
        ("(0 - 2147483647 - 1) / -1", -(2**31)),
        ("1 << 33", 2),
        ("-8 >> 1", -4),
        ("~0", -1),
        ("!5", 0),
        ("!0", 1),
        ("3 && 0", 0),
        ("0 || -2", 1),
        ("6 & 3 | 8 ^ 1", 11),
        ("select(2, 10, 20)", 10),
        ("select(0, 10, 20)", 20),
        ("0x7fffffff", 2**31 - 1),
        ("true + true", 2),
    ],
)
def test_arithmetic(expr, value):
    assert ev(expr) == value


def test_wrap_is_idempotent():
    for v in [0, 1, -1, 2**31, 2**32 + 5, -(2**40)]:
        assert wrap(wrap(v)) == wrap(v)
        assert -(2**31) <= wrap(v) < 2**31


def test_comparisons():
    for op, f in [("<", int.__lt__), ("<=", int.__le__), (">", int.__gt__), (">=", int.__ge__),
                  ("==", int.__eq__), ("!=", int.__ne__)]:
        assert binop(op, 3, 4) == int(f(3, 4))


def test_trace_records_branches_loops_and_addresses():
    prog = parse("""
        public int n; secret int s; public int[4] a; secret int[4] b;
        for i in 0 .. n { b[i] := a[3 - i] + s; }
        if (n > 1) { skip; } else { skip; }
    """)
    res = run(prog, {"n": 2, "s": 9, "a": [1, 2, 3, 4]})
    assert res.trace == [
        ("loop", 3, 9, 2),
        ("load", "a", 3), ("store", "b", 0),
        ("load", "a", 2), ("store", "b", 1),
        ("branch", 4, 9, True),
    ]
    assert res.arrays["b"] == [13, 12, 0, 0]
    assert res.error is None


def test_select_evaluates_both_arms():
    prog = parse("secret int c; secret int r; public int[2] a; r := select(c, a[0], a[1]);")
    for c in (0, 1):
        res = run(prog, {"c": c})
        assert [e for e in res.trace if e[0] == "load"] == [("load", "a", 0), ("load", "a", 1)]


def test_logical_operators_do_not_short_circuit():
    prog = parse("public int r; public int[1] a; r := 0 && a[0]; r := 1 || a[0];")
    assert run(prog).trace == [("load", "a", 0), ("load", "a", 0)]


def test_cost_model_is_fixed_per_operation():
    prog = parse("public int x; secret int s; x := x + 1; s := s / 3;")
    res = run(prog, {"s": 100})
    expected = 2 * COSTS["var"] + COSTS["const"] * 2 + COSTS["+"] + COSTS["/"] + 2 * COSTS["assign"]
    assert res.cost == expected
    assert res.cost == run(prog, {"s": -5}).cost


def test_loop_bounds_evaluated_once_and_empty_ranges():
    prog = parse("public int n; public int c; for i in 0 .. n { n := n + 1; c := c + 1; }")
    res = run(prog, {"n": 3})
    assert res.scalars["c"] == 3
    prog2 = parse("public int c; for i in 5 .. 2 { c := c + 1; }")
    res2 = run(prog2)
    assert res2.scalars["c"] == 0 and res2.trace == [("loop", 1, 15, 0)]


def test_out_of_bounds_is_recorded():
    prog = parse("public int i; public int[2] a; public int x; x := 1; a[i] := 5; x := 2;")
    res = run(prog, {"i": 2})
    assert res.error and "out of bounds" in res.error
    assert res.trace[-1][0] == "error"
    assert res.scalars["x"] == 1


def test_step_limit():
    prog = parse("public int x; for i in 0 .. 1000 { for j in 0 .. 1000 { x := x + 1; } }")
    res = run(prog, max_steps=500)
    assert res.error and "step limit" in res.error


def test_inputs_and_initialisers():
    prog = parse("public int a = 4; secret int[3] k = {1, 2, 3}; public int[2] z;")
    res = run(prog, {"z": 7})
    assert res.scalars["a"] == 4 and res.arrays["k"] == [1, 2, 3] and res.arrays["z"] == [7, 7]
    assert run(prog, {"a": 9}).scalars["a"] == 9
    with pytest.raises(ValueError):
        run(prog, {"nope": 1})
    with pytest.raises(ValueError):
        run(prog, {"k": [1, 2]})


def test_observation_contains_only_public_outputs():
    prog = parse("public int p; secret int s; p := 1; s := 2;")
    obs = run(prog).observation()
    assert obs.public_out == (("p", 1),)
