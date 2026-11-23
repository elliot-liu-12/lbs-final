"""Reading the expectation headers of the example programs.

Each example starts with comment lines such as::

    // expect-ct: reject CT-BRANCH
    // expect-ni: accept
    // leaks: yes
    // witness: pw=0x5eed1234 | pw=0      (optional: secret inputs of two runs)

``expect-*`` give the manually justified verdict and the exact set of
diagnostic codes; ``leaks`` is the manually justified ground truth for the
constant-time observation model (does any pair of runs with equal public
inputs produce different observations?).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"


@dataclass
class Expectation:
    path: Path
    ct_accept: bool
    ct_codes: FrozenSet[str]
    ni_accept: bool
    ni_codes: FrozenSet[str]
    leaks: bool
    witness: Optional[Tuple[Dict[str, object], Dict[str, object]]] = None

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def category(self) -> str:
        return self.path.parent.name


def _verdict(text: str) -> Tuple[bool, FrozenSet[str]]:
    words = text.split()
    if not words or words[0] not in ("accept", "reject"):
        raise ValueError(f"bad verdict {text!r}")
    return words[0] == "accept", frozenset(words[1:])


def _assignments(text: str) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for item in text.split():
        name, raw = item.split("=", 1)
        if "," in raw:
            out[name] = [int(x, 0) for x in raw.split(",")]
        else:
            out[name] = int(raw, 0)
    return out


def read_expectation(path: Path) -> Expectation:
    fields: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith("//"):
            break
        body = line[2:].strip()
        if ":" in body:
            key, val = body.split(":", 1)
            fields[key.strip()] = val.strip()
    ct_ok, ct_codes = _verdict(fields["expect-ct"])
    ni_ok, ni_codes = _verdict(fields["expect-ni"])
    witness = None
    if "witness" in fields:
        a, b = fields["witness"].split("|")
        witness = (_assignments(a), _assignments(b))
    return Expectation(path, ct_ok, ct_codes, ni_ok, ni_codes, fields["leaks"] == "yes", witness)


def all_examples() -> List[Expectation]:
    return [read_expectation(p) for p in sorted(EXAMPLES_DIR.glob("*/*.ct"))]
