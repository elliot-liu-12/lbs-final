import pytest

from ctcheck import Mode, check, parse

DECLS = """
public int p; public int q;
secret int s; secret int t;
public int[4] pa; secret int[4] sa;
"""


def codes(body, mode=Mode.CT, **kw):
    return check(parse(DECLS + body), mode, **kw).codes


def accepts(body, mode=Mode.CT, **kw):
    return codes(body, mode, **kw) == []


# ------------------------------------------------------------------ explicit flows
@pytest.mark.parametrize("body", ["s := p;", "s := s + t;", "p := q * 2;", "sa[0] := s;", "sa[p & 3] := pa[q & 3];"])
def test_allowed_assignments(body):
    assert accepts(body)


@pytest.mark.parametrize("body", ["p := s;", "p := s * 0;", "pa[0] := t;", "p := select(s, 1, 1);", "p := sa[0];"])
def test_explicit_flow_rejected_in_both_modes(body):
    assert codes(body) == ["EXPLICIT-FLOW"]
    assert codes(body, Mode.NI) == ["EXPLICIT-FLOW"]


# ------------------------------------------------------------------ CT rules
def test_secret_guard():
    assert codes("if (s) { t := 1; }") == ["CT-BRANCH"]
    assert accepts("if (s) { t := 1; }", Mode.NI)


def test_secret_guard_in_else_if():
    assert codes("if (p) { skip; } else if (s == 1) { skip; }") == ["CT-BRANCH"]


def test_secret_loop_bound():
    assert codes("for i in 0 .. s { t := t + i; }") == ["CT-LOOP"]
    assert codes("for i in s .. 4 { skip; }") == ["CT-LOOP"]
    assert accepts("for i in 0 .. s { t := t + i; }", Mode.NI)


@pytest.mark.parametrize("body", ["t := sa[s & 3];", "t := pa[s & 3];", "sa[s & 3] := 1;", "t := sa[sa[0] & 3];"])
def test_secret_index(body):
    assert "CT-INDEX" in codes(body)


def test_secret_index_into_public_array_is_also_an_explicit_flow():
    assert codes("p := pa[s & 3];") == ["CT-INDEX", "EXPLICIT-FLOW"]
    assert codes("p := pa[s & 3];", Mode.NI) == ["EXPLICIT-FLOW"]


def test_public_index_from_public_array():
    assert accepts("sa[pa[p & 3] & 3] := s;")


def test_select_allows_secret_condition():
    assert accepts("t := select(s > 3, s, t);")


def test_loop_variable_is_public_in_ct_mode():
    assert accepts("for i in 0 .. 4 { p := p + i; sa[i] := s; if (i == 2) { skip; } }")


def test_errors_are_all_reported():
    res = check(parse(DECLS + "p := s; if (s) { skip; } for i in 0 .. t { skip; } t := pa[s & 3];"))
    assert res.codes == ["CT-BRANCH", "CT-INDEX", "CT-LOOP", "EXPLICIT-FLOW"]
    assert [d.loc.line for d in res.diagnostics] == sorted(d.loc.line for d in res.diagnostics)


def test_diagnostics_name_secret_sources():
    (d,) = check(parse(DECLS + "if (s + t > p) { skip; }")).diagnostics
    assert d.sources == ("s", "t")
    assert "`s`" in d.message and "`t`" in d.message


# ------------------------------------------------------------------ NI mode
def test_ni_implicit_flows():
    assert codes("if (s) { p := 1; }", Mode.NI) == ["IMPLICIT-FLOW"]
    assert codes("for i in 0 .. s { p := p + 1; }", Mode.NI) == ["IMPLICIT-FLOW"]
    assert codes("if (s) { pa[0] := 1; }", Mode.NI) == ["IMPLICIT-FLOW"]
    assert codes("if (p) { if (s) { skip; } p := 1; }", Mode.NI) == []


def test_ni_secret_index_taints_value_and_location():
    assert accepts("t := sa[s & 3];", Mode.NI)
    assert codes("pa[s & 3] := 1;", Mode.NI) == ["EXPLICIT-FLOW"]
    assert accepts("sa[s & 3] := 1;", Mode.NI)


def test_ni_loop_variable_inherits_bound_label():
    assert codes("for i in 0 .. s { p := i; }", Mode.NI) == ["EXPLICIT-FLOW"]


# ------------------------------------------------------------------ variable-time division
def test_vartime_division_flag():
    assert accepts("t := s / 3;")
    assert check(parse(DECLS + "t := s % p;"), variable_time_div=True).codes == ["CT-VARTIME"]
    assert check(parse(DECLS + "q := p / 3;"), variable_time_div=True).ok


# ------------------------------------------------------------------ well-formedness
@pytest.mark.parametrize(
    "src,code",
    [
        ("public int x; y := 1;", "UNDECLARED"),
        ("public int x; x := y;", "UNDECLARED"),
        ("public int x; x := z[0];", "UNDECLARED"),
        ("public int x; public int[2] a; a := 1;", "KIND"),
        ("public int x; public int[2] a; x := a;", "KIND"),
        ("public int x; x[0] := 1;", "KIND"),
        ("public int x; x := x[0];", "KIND"),
        ("public int x; secret int x;", "DUP-DECL"),
        ("public int[2] a = {1, 2, 3};", "ARRAY-INIT"),
        ("public int[0] a;", "ARRAY-SIZE"),
        ("public int x; for i in 0 .. 2 { i := 1; }", "LOOPVAR-ASSIGN"),
        ("public int x; for x in 0 .. 2 { skip; }", "LOOPVAR-SHADOW"),
        ("public int x; for i in 0 .. 2 { for i in 0 .. 2 { skip; } }", "LOOPVAR-SHADOW"),
        ("public int x; x := len(b);", "UNDECLARED"),
    ],
)
def test_well_formedness(src, code):
    assert code in check(parse(src)).codes


def test_loop_variable_scope_ends_with_loop():
    assert "UNDECLARED" in check(parse("public int x; for i in 0 .. 2 { skip; } x := i;")).codes
