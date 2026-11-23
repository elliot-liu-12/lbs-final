import pytest

from ctcheck import ast as A
from ctcheck import parse, pretty
from ctcheck.examples import all_examples
from ctcheck.parser import ParseError


def body(src):
    return parse(src).body


def test_declarations():
    p = parse("public int n = -3; secret int[4] k = {1, 0x10, -2, 3,}; secret int s;")
    n, k, s = p.decls
    assert (n.label, n.name, n.init) == (A.Label.PUBLIC, "n", -3)
    assert (k.label, k.size, k.init) == (A.Label.SECRET, 4, [1, 16, -2, 3])
    assert s.init is None


def test_precedence_matches_c():
    (stmt,) = body("public int x; x := 1 + 2 * 3 << 1 & 7 == 0 || 1;")
    assert pretty.expr(stmt.value) == "((((1 + (2 * 3)) << 1) & (7 == 0)) || 1)"


def test_unary_and_binary_minus():
    (stmt,) = body("public int x; x := -x - -1;")
    assert isinstance(stmt.value, A.BinOp) and stmt.value.op == "-"
    assert isinstance(stmt.value.left, A.UnOp) and isinstance(stmt.value.right, A.UnOp)


def test_else_if_chain():
    (s,) = body("public int x; if (x) { skip; } else if (x == 1) { x := 2; } else { x := 3; }")
    assert isinstance(s, A.If) and isinstance(s.other[0], A.If)
    assert len(s.other[0].other) == 1


def test_for_select_len_and_comments():
    src = """
    public int[3] a;  // trailing comment
    secret int s;
    /* block
       comment */
    for i in 0 .. len(a) { s := select(true, a[i], false); }
    """
    (f,) = body(src)
    assert isinstance(f, A.For) and isinstance(f.hi, A.Len)
    assert isinstance(f.body[0].value, A.Select)


def test_locations():
    p = parse("public int x;\n\n  x := 1;")
    assert p.body[0].loc == A.Loc(3, 3)


@pytest.mark.parametrize(
    "src,line",
    [
        ("public int x\nx := 1;", 2),
        ("public int x; x := ;", 1),
        ("public int x; if x { skip; }", 1),
        ("public int x; x := 1 $ 2;", 1),
        ("secret int if;", 1),
    ],
)
def test_syntax_errors_have_locations(src, line):
    with pytest.raises(ParseError) as ei:
        parse(src)
    assert ei.value.loc.line == line


def test_unexpected_eof():
    with pytest.raises(ParseError):
        parse("public int x; if (x) {")


@pytest.mark.parametrize("ex", all_examples(), ids=lambda e: e.name)
def test_pretty_round_trip(ex):
    p = parse(ex.path.read_text())
    printed = pretty.program(p)
    assert pretty.program(parse(printed)) == printed
