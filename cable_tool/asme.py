"""ASME drawing-format rules and the drawing format checker.

Values follow the ASME Y14 series as commonly applied:

* Y14.1   sheet sizes, margins, zoning, title block, continuation-sheet title block
* Y14.2   line weights (thin 0.3 mm / thick 0.6 mm) and minimum letter heights
* Y14.5   dimensioning: tolerances stated, 3:1 arrowheads, extension-line gaps
* Y14.34  parts list (find numbers, QTY REQD, CAGE, PART OR IDENTIFYING NO, NOMENCLATURE, NOTE)
* Y14.35  revision block
* Y14.100 notes (general and flag notes), "UNLESS OTHERWISE SPECIFIED" block

The numbers below are the defaults this tool draws with; check them against the edition of each standard
your organization works to and adjust them here.
"""

from __future__ import annotations

from dataclasses import dataclass

IN = 72.0
MM = 72.0 / 25.4

# Helvetica cap height as a fraction of the font size (letter height is measured on capitals).
CAP_RATIO = 0.718

# Minimum letter heights (inches), ASME Y14.2 Table 1
LETTER_HEIGHT = {
    "title": 0.24,       # drawing title, drawing number in title block, sheet size letter
    "zone": 0.24,        # zone letters and numerals in the margin
    "general": 0.12,     # dimensions, notes, tables, parts list, revisions, view titles
    "heading": 0.10,     # drawing block headings (title block captions)
}

# Line weights, ASME Y14.2 (absolute pen widths in points)
THIN = 0.3 * MM          # 0.85 pt: dimension, extension, leader lines, tables, hatching
THICK = 0.6 * MM         # 1.70 pt: visible outlines, borders, block outlines
PEN_MAX = 3.0            # canvas widths below this are pen weights (never scaled); above are geometry

# Dimension arrowheads 3:1 (length : width)
ARROW_LENGTH = 6.0
ARROW_HALF_ANGLE = 9.46  # degrees: atan(0.5 / 3)


def font_for(role: str) -> float:
    """Font size (pt) whose cap height meets the minimum for ``role``, with a small safety margin."""
    return LETTER_HEIGHT[role] * IN / CAP_RATIO * 1.02


TITLE_FONT = font_for("title")      # ~24.6 pt
ZONE_FONT = font_for("zone")
BODY_FONT = font_for("general")     # ~12.3 pt
HEADING_FONT = font_for("heading")  # ~10.2 pt

# Views are laid out with this body text size, then placed at a scale that brings it up to BODY_FONT.
VIEW_TEXT = 7.0
MIN_VIEW_SCALE = BODY_FONT / VIEW_TEXT

# Sheet sizes in order of preference, per family (Y14.1 / ISO 5457)
SHEET_SIZES: dict[str, tuple[str, float, float]] = {
    "ANSI B (17 x 11 in)": ("B", 17 * IN, 11 * IN),
    "ANSI C (22 x 17 in)": ("C", 22 * IN, 17 * IN),
    "ANSI D (34 x 22 in)": ("D", 34 * IN, 22 * IN),
    "ANSI E (44 x 34 in)": ("E", 44 * IN, 34 * IN),
    "ISO A3 (420 x 297 mm)": ("A3", 420 * MM, 297 * MM),
    "ISO A2 (594 x 420 mm)": ("A2", 594 * MM, 420 * MM),
    "ISO A1 (841 x 594 mm)": ("A1", 841 * MM, 594 * MM),
    "ISO A0 (1189 x 841 mm)": ("A0", 1189 * MM, 841 * MM),
}
DEFAULT_SHEET = "ANSI B (17 x 11 in)"


def larger_sizes(name: str) -> list[str]:
    """``name`` followed by the larger sizes of the same family."""
    names = list(SHEET_SIZES)
    family = "ANSI" if name.startswith("ANSI") else "ISO"
    same = [n for n in names if n.startswith(family)]
    return same[same.index(name):]


# Sheet format geometry (points)
MARGIN = 0.375 * IN          # trim edge to border
ZONE_BAND = 0.375 * IN       # border to inner frame (holds zone letters/numerals)
TB_W = 6.62 * IN             # title block width (Y14.1 A-C size; also used for D/E here)
TB_H = 2.3 * IN
TB_LEFT_W = 2.62 * IN        # approvals part of the title block
CONT_TB_H = 0.85 * IN        # continuation-sheet title block height
TOL_W = 3.1 * IN            # "UNLESS OTHERWISE SPECIFIED" block
APP_W = 2.25 * IN            # application block

DEFAULT_TOLERANCE_LINES = [
    "UNLESS OTHERWISE SPECIFIED:",
    "DIMENSIONS ARE IN {UNITS_NAME}",
    "LENGTH TOLERANCE ±{TOL}",
    "INTERPRET PER ASME Y14.5",
    "DO NOT SCALE DRAWING",
]


@dataclass
class FormatIssue:
    severity: str
    item: str
    message: str


def _walk_text(group, scale: float, sheet_no: int, out: list):
    from .canvas import Group, Text

    for it in group.items:
        if isinstance(it, Group):
            _walk_text(it, scale * it.scale, sheet_no, out)
        elif isinstance(it, Text) and it.s.strip():
            out.append((it, it.size * scale * CAP_RATIO / IN, sheet_no))


def check_format(sheets, design) -> list[FormatIssue]:
    """Check generated sheets against the ASME format rules above."""
    issues: list[FormatIssue] = []
    texts: list = []
    for n, sheet in enumerate(sheets, start=1):
        _walk_text(sheet.root, 1.0, n, texts)
    small: dict[int, list[float]] = {}
    for t, cap, n in texts:
        need = LETTER_HEIGHT.get(t.role, LETTER_HEIGHT["general"])
        if cap + 1e-4 < need:
            small.setdefault(n, []).append(cap)
    for n, caps in sorted(small.items()):
        issues.append(FormatIssue("WARNING", f"SHEET {n}",
                                  f"{len(caps)} text item(s) are below the ASME Y14.2 minimum letter height "
                                  f"(smallest {min(caps):.3f} in). Use a larger sheet size."))

    tb = design.title_block
    required = {"drawing_number": "drawing number", "title": "title", "drawn_by": "DRAWN name",
                "date": "DRAWN date", "company": "company name"}
    for f, label in required.items():
        if not str(getattr(tb, f) or "").strip():
            issues.append(FormatIssue("WARNING", "TITLE BLOCK", f"No {label} in the title block."))
    for f, label in {"cage_code": "CAGE code", "checked_by": "CHECKED name", "approved_by": "APPROVED name"}.items():
        if not str(getattr(tb, f) or "").strip():
            issues.append(FormatIssue("INFO", "TITLE BLOCK", f"No {label} in the title block."))
    if not design.revisions:
        issues.append(FormatIssue("INFO", "REVISION BLOCK",
                                  "No revision history entered; the revision block shows the current revision only."))
    elif design.revisions[-1].rev != (tb.revision or "-"):
        issues.append(FormatIssue("WARNING", "REVISION BLOCK",
                                  f"Title block REV '{tb.revision}' doesn't match the latest revision "
                                  f"'{design.revisions[-1].rev}'."))

    meta = getattr(sheets[0], "meta", {}) if sheets else {}
    balloons, parts = set(meta.get("balloons", ())), set(meta.get("find_numbers", ()))
    for n in sorted(balloons - parts):
        issues.append(FormatIssue("ERROR", "PARTS LIST", f"Find number {n} is ballooned but isn't in the parts list."))
    missing = sorted(parts - balloons)
    if missing:
        issues.append(FormatIssue("INFO", "PARTS LIST",
                                  "Find numbers not ballooned on the assembly view (listed in tables instead): "
                                  + ", ".join(str(n) for n in missing) + "."))
    for w in meta.get("layout_warnings", ()):
        issues.append(FormatIssue("WARNING", "LAYOUT", w))
    return issues
