"""Connector insert layouts (contact positions on the mating face) and the face views drawn from them.

Layouts come from ``data/d38999_insert_layouts.csv``: MIL-DTL-38999 Series III arrangements (MIL-STD-1560), extracted
from the insert-arrangement drawings by ``tools/extract_insert_layouts.py``. Only arrangements whose every contact is
labelled in the source drawing are included.

MIL-STD-1560 draws each arrangement as the front (engaging) face of the pin insert; a socket insert's front face is
its mirror image, so views of socket connectors are mirrored to show the actual part. The source drawings don't show the master keyway, so the face views don't either.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .asme import THICK, THIN
from .canvas import Group, fit_text

DATA = Path(__file__).resolve().parent / "data" / "d38999_insert_layouts.csv"

# D38999/<class 2 digits><finish><shell letter><arrangement><contact type><key>[-LC]
_D38999 = re.compile(r"^D38999/(\d{2})([A-Z])([A-J])(\d{1,2})([PSAB])([NABCDE])", re.I)
SHELL_SIZE = {"A": 9, "B": 11, "C": 13, "D": 15, "E": 17, "F": 19, "G": 21, "H": 23, "J": 25}


@dataclass(frozen=True)
class Cavity:
    contact: str
    x: float          # cavity centre, relative to the insert radius (+x right, +y up), pin-insert face
    y: float
    size: str         # contact size (22D, 20, 16, 12, 10)
    d: float          # cavity symbol diameter, relative to the insert radius
    lx: float         # label centre
    ly: float
    h: float          # label font size, relative to the insert radius


@dataclass(frozen=True)
class InsertInfo:
    arrangement: str  # e.g. "D19" (shell letter + MIL-STD-1560 arrangement number)
    shell_size: int
    contact_type: str  # "pin" or "socket"
    key: str           # key position letter (N = normal)

    @property
    def insert_name(self) -> str:
        return f"{self.shell_size}-{self.arrangement[1:].zfill(2)}"


@lru_cache(maxsize=1)
def layouts() -> dict[str, tuple[Cavity, ...]]:
    out: dict[str, list[Cavity]] = {}
    if not DATA.exists():
        return {}
    with open(DATA, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["Arrangement"], []).append(Cavity(
                r["Contact"], float(r["X"]), float(r["Y"]), r["Size"], float(r["D"]),
                float(r["LX"]), float(r["LY"]), float(r["H"])))
    return {k: tuple(v) for k, v in out.items()}


def insert_info(pn: str) -> InsertInfo | None:
    """Arrangement, contact type and key of a D38999 Series III part number, or None if it isn't one."""
    m = _D38999.match((pn or "").strip())
    if not m:
        return None
    _cls, _finish, shell, arr, ctype, key = m.groups()
    shell = shell.upper()
    return InsertInfo(f"{shell}{int(arr)}", SHELL_SIZE[shell], "pin" if ctype.upper() in "PA" else "socket", key.upper())


def layout_for(pn: str) -> tuple[InsertInfo, tuple[Cavity, ...]] | None:
    info = insert_info(pn)
    if info is None:
        return None
    cavs = layouts().get(info.arrangement)
    return (info, cavs) if cavs else None


def face_view(ref: str, pn: str, used: set[str], text: float) -> Group | None:
    """Pinout of connector ``ref`` as the part ``pn`` itself looks from its front (engaging) face: every cavity with
    its contact label, wired contacts filled, unused (NC) contacts open. A socket insert is drawn as the mirror image
    of the MIL-STD-1560 (pin insert) arrangement, so the view always matches the part called out.
    ``text`` is the label text size; the insert is drawn big enough that labels keep their catalogue spacing.
    Returns None when no layout is known for ``pn``."""
    found = layout_for(pn)
    if not found:
        return None
    info, cavs = found
    mirror = -1 if info.contact_type == "socket" else 1
    label_h = sorted(c.h for c in cavs)[len(cavs) // 2]
    R = max(42.0, text / label_h)
    g = Group(layer="FACE_VIEWS")
    g.circle(0, 0, R, fill="#ffffff", width=THICK)
    g.circle(0, 0, R * 1.12, width=THIN)                      # coupling ring / shell
    for c in cavs:
        x, y = mirror * c.x * R, -c.y * R                     # canvas y is down
        r = max(c.d * R / 2, 1.6)
        g.circle(x, y, r, fill="#000000" if c.contact in used else "#ffffff", width=THIN)
        g.text(mirror * c.lx * R, -c.ly * R + text * 0.36, c.contact, size=text, anchor="middle")
    y = R * 1.12 + text + 6
    for k, line in enumerate((f"{ref} PINOUT, FRONT FACE",
                              fit_text(pn, text, R * 2.4),
                              f"INSERT {info.insert_name}, KEY {info.key}",
                              f"{info.contact_type.upper()} CONTACTS")):
        g.text(0, y, line, size=text, anchor="middle", bold=k == 0)
        y += text + 3
    return g
