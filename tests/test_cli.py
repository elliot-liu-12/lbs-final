import json

from ctcheck.cli import main
from ctcheck.examples import EXAMPLES_DIR

SAFE = str(EXAMPLES_DIR / "safe" / "ct_cswap.ct")
LEAKY = str(EXAMPLES_DIR / "leaky" / "leak_sbox_lookup.ct")
MAGIC = str(EXAMPLES_DIR / "leaky" / "leak_magic_value.ct")


def test_check_exit_codes(capsys):
    assert main(["check", SAFE]) == 0
    assert main(["check", SAFE, LEAKY]) == 1
    out = capsys.readouterr().out
    assert "ACCEPTED" in out and "REJECTED" in out and "[CT-INDEX]" in out
    assert main(["check", "--mode", "ni", LEAKY]) == 0


def test_check_json(capsys):
    main(["check", "--json", LEAKY])
    (report,) = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and report["diagnostics"][0]["code"] == "CT-INDEX"
    assert report["diagnostics"][0]["sources"] == ["key"]


def test_check_parse_error(tmp_path, capsys):
    bad = tmp_path / "bad.ct"
    bad.write_text("public int x x := 1;")
    assert main(["check", str(bad), SAFE]) == 2
    assert "unexpected" in capsys.readouterr().err


def test_run(capsys):
    assert main(["run", SAFE, "--set", "swap=1", "--set", "x=1,2,3,4,5,6,7,8", "--trace"]) == 0
    out = capsys.readouterr().out
    assert "secret y = [1, 2, 3, 4, 5, 6, 7, 8]" in out and "load x[0]" in out


def test_compare(capsys):
    assert main(["compare", SAFE, "--trials", "50"]) == 0
    assert main(["compare", LEAKY]) == 1
    assert main(["compare", MAGIC, "--a", "pw=0x5eed1234", "--b", "pw=0"]) == 1
    assert "LEAK WITNESSED" in capsys.readouterr().out
