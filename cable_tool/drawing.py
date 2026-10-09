"""Lay out the cable drawing in ASME Y14 format.

Sheet 1   General and flag notes (Y14.100), parts list (Y14.34) above the title block, revision block (Y14.35),
          application block, "UNLESS OTHERWISE SPECIFIED" block and full title block.
Sheet 2   Assembly view (connector ends, backshells, boots, ID labels, splices, dimensions, find-number balloons
          and flag notes), with each connector's pinout (front face, NC positions open) under it.
Sheet 3   Wiring diagram (Y14.15 style): connector pin-outs including NC positions, wires point to point or to
          splice nodes, twisted pairs, shields and shield terminations.
Sheet 4+  Wire list, wire groups and shields, splices, label schedule, and any parts-list continuation.
Every sheet has a zoned border (Y14.1), a reverse-oriented drawing-number block, and a title block
(continuation sheets use the reduced Y14.1 continuation title block).

Text never goes below the Y14.2 minimum letter heights: views and tables are drawn with VIEW_TEXT-size text and
placed at a scale of at least MIN_VIEW_SCALE. When something doesn't fit at that scale the drawing moves up to
the next sheet size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .asme import (
    APP_W,
    BODY_FONT,
    CONT_TB_H,
    DEFAULT_SHEET,
    DEFAULT_TOLERANCE_LINES,
    HEADING_FONT,
    MARGIN,
    MIN_VIEW_SCALE,
    SHEET_SIZES,
    TB_H,
    TB_LEFT_W,
    TB_W,
    THICK,
    THIN,
    TITLE_FONT,
    TOL_W,
    VIEW_TEXT,
    ZONE_BAND,
    ZONE_FONT,
    larger_sizes,
)
from .bom import BomItem, build_bom, compress_refs, item_numbers
from .canvas import Group, Sheet, fit_text, text_width
from .inserts import face_view, layout_for
from .model import (
    SHIELD_BACKSHELL,
    SHIELD_FLOAT,
    UNIT_NAMES,
    CableDesign,
    ConnectorEnd,
    Wire,
    fmt_dia,
    fmt_length,
    natural_key,
    parse_shield_term,
)

__all__ = ["DEFAULT_SHEET", "SHEET_SIZES", "build_drawing", "assign_sides", "wiring_diagram", "assembly_view"]

IN = 72.0
PAD = 12.0
ASSEMBLY_SHEET, WIRING_SHEET, FIRST_TABLE_SHEET = 2, 3, 4
SHADE = "#d9d9d9"
HEADER_FILL = "#eeeeee"
T = VIEW_TEXT                   # body text size inside views and tables (scaled up to >= 0.12 in)
REV_W = 6.0 * IN                # revision block width
DWG_BLOCK = (2.75 * IN, 0.5 * IN)


@dataclass
class Frame:
    x0: float
    y0: float
    x1: float
    y1: float
    tb_h: float = TB_H
    tb_w: float = TB_W

    @property
    def tb_top(self) -> float:
        return self.y1 - self.tb_h

    @property
    def tb_left(self) -> float:
        return self.x1 - self.tb_w


# ---------------------------------------------------------------------------
# Sheet format: border, zones, reverse drawing-number block (Y14.1)
# ---------------------------------------------------------------------------
def draw_frame(g: Group, w: float, h: float) -> Frame:
    g.rect(MARGIN, MARGIN, w - 2 * MARGIN, h - 2 * MARGIN, width=THIN)
    f = Frame(MARGIN + ZONE_BAND, MARGIN + ZONE_BAND, w - MARGIN - ZONE_BAND, h - MARGIN - ZONE_BAND)
    g.rect(f.x0, f.y0, f.x1 - f.x0, f.y1 - f.y0, width=THICK)
    ncols = max(2, round(w / (4.25 * IN)))
    nrows = max(2, round(h / (5.5 * IN)))
    cw, rh = (f.x1 - f.x0) / ncols, (f.y1 - f.y0) / nrows
    base = ZONE_FONT * 0.36
    for i in range(ncols):  # zone numbers increase right to left
        cx = f.x0 + (i + 0.5) * cw
        label = str(ncols - i)
        g.text(cx, MARGIN + ZONE_BAND / 2 + base, label, size=ZONE_FONT, anchor="middle", role="zone")
        g.text(cx, h - MARGIN - ZONE_BAND / 2 + base, label, size=ZONE_FONT, anchor="middle", role="zone")
        if i:
            x = f.x0 + i * cw
            g.line(x, MARGIN, x, f.y0, width=THIN)
            g.line(x, f.y1, x, h - MARGIN, width=THIN)
    for j in range(nrows):  # zone letters increase bottom to top
        cy = f.y0 + (j + 0.5) * rh
        label = "ABCDEFGHJK"[nrows - 1 - j]
        g.text(MARGIN + ZONE_BAND / 2, cy + base, label, size=ZONE_FONT, anchor="middle", role="zone")
        g.text(w - MARGIN - ZONE_BAND / 2, cy + base, label, size=ZONE_FONT, anchor="middle", role="zone")
        if j:
            y = f.y0 + j * rh
            g.line(MARGIN, y, f.x0, y, width=THIN)
            g.line(f.x1, y, w - MARGIN, y, width=THIN)
    return f


def draw_reverse_block(g: Group, f: Frame, design: CableDesign) -> float:
    """Drawing number block in the upper-left corner, rotated 180° (Y14.1). Returns its bottom y."""
    w, h = DWG_BLOCK
    x, y = f.x0, f.y0
    g.rect(x, y, w, h, width=THICK)
    text = f"{design.title_block.drawing_number or '—'}  REV {current_rev(design)}"
    g.text(x + w / 2, y + h / 2 - BODY_FONT * 0.36, fit_text(text, BODY_FONT, w - 8, True), size=BODY_FONT,
           bold=True, anchor="middle", rotation=180)
    return y + h


def current_rev(design: CableDesign) -> str:
    return design.revisions[-1].rev if design.revisions else (design.title_block.revision or "-")


# ---------------------------------------------------------------------------
# Title block, continuation title block, tolerance and application blocks
# ---------------------------------------------------------------------------
def _cell(g: Group, x, y, w, h, caption, value, size=BODY_FONT, bold=False, center=False, role="general"):
    g.rect(x, y, w, h, width=THIN)
    if caption:
        g.text(x + 3, y + HEADING_FONT * 0.85, caption, size=HEADING_FONT, role="heading")
    if value:
        value = fit_text(value, size, w - 8, bold)
        if center:
            g.text(x + w / 2, y + h - 5, value, size=size, bold=bold, anchor="middle", role=role)
        else:
            g.text(x + 5, y + h - 5, value, size=size, bold=bold, role=role)


def _wrap_fit(text: str, size: float, width: float, max_lines: int) -> list[str]:
    lines = wrap(text, size, width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit_text(lines[-1] + " …", size, width, True)
    return lines


def _number_rows(g: Group, x: float, y: float, w: float, design: CableDesign, size_letter: str, sheet_no: int,
                 total: int, h1: float, h2: float) -> None:
    """SIZE | CAGE CODE | DWG NO | REV over SCALE | WEIGHT | SHEET (shared by full and continuation blocks)."""
    tb = design.title_block
    size_w, cage_w, rev_w = 0.6 * IN, 1.0 * IN, 0.6 * IN
    _cell(g, x, y, size_w, h1, "SIZE", size_letter, size=TITLE_FONT, bold=True, center=True, role="title")
    _cell(g, x + size_w, y, cage_w, h1, "CAGE CODE", tb.cage_code, center=True)
    _cell(g, x + size_w + cage_w, y, w - size_w - cage_w - rev_w, h1, "DWG NO.", tb.drawing_number,
          size=TITLE_FONT, bold=True, role="title")
    _cell(g, x + w - rev_w, y, rev_w, h1, "REV", current_rev(design), bold=True, center=True)
    y += h1
    third = w / 3
    _cell(g, x, y, third, h2, "SCALE", tb.scale or "NONE")
    _cell(g, x + third, y, third, h2, "WEIGHT", tb.weight)
    _cell(g, x + 2 * third, y, third, h2, "SHEET", f"{sheet_no} OF {total}", bold=True)


def draw_title_block(g: Group, f: Frame, design: CableDesign, size_letter: str, sheet_no: int, total: int) -> None:
    tb = design.title_block
    x, y = f.tb_left, f.tb_top
    g.rect(x, y, TB_W, TB_H, width=THICK, fill="#ffffff")
    # Left: contract number and approvals (NAME / DATE)
    lw = TB_LEFT_W
    _cell(g, x, y, lw, 0.42 * IN, "CONTRACT NO.", tb.contract_number)
    ry = y + 0.42 * IN
    g.rect(x, ry, lw, 0.22 * IN, width=THIN)
    g.text(x + 4, ry + HEADING_FONT, "APPROVALS", size=HEADING_FONT, role="heading")
    g.text(x + lw * 0.6, ry + HEADING_FONT, "DATE", size=HEADING_FONT, role="heading")
    ry += 0.22 * IN
    row_h = (TB_H - 0.64 * IN) / 4
    for label, name, date in (("DRAWN", tb.drawn_by, tb.date), ("CHECKED", tb.checked_by, tb.checked_date),
                              ("ENGR", tb.engineer, tb.engineer_date), ("APPROVED", tb.approved_by, tb.approved_date)):
        _cell(g, x, ry, lw * 0.56, row_h, label, name)
        _cell(g, x + lw * 0.56, ry, lw * 0.44, row_h, "", date)
        ry += row_h
    # Right: design activity, title, number rows
    rx, rw = x + lw, TB_W - lw
    _cell(g, rx, y, rw, 0.4 * IN, "", "")
    for i, line in enumerate(_wrap_fit((tb.company or "").upper(), BODY_FONT, rw - 10, 2)):
        g.text(rx + rw / 2, y + 13 + i * (BODY_FONT + 1), line, size=BODY_FONT, bold=True, anchor="middle")
    ty = y + 0.4 * IN
    title_h = TB_H - 0.4 * IN - 0.55 * IN - 0.4 * IN
    _cell(g, rx, ty, rw, title_h, "TITLE", "")
    lines = _wrap_fit((tb.title or "").upper(), TITLE_FONT, rw - 10, 2)
    for i, line in enumerate(lines):
        base = ty + HEADING_FONT + 2 + (title_h - HEADING_FONT - 2) / 2 + TITLE_FONT * 0.36 + (i - (len(lines) - 1) / 2) * (TITLE_FONT + 1)
        g.text(rx + rw / 2, base, line, size=TITLE_FONT, bold=True, anchor="middle", role="title")
    _number_rows(g, rx, ty + title_h, rw, design, size_letter, sheet_no, total, h1=0.55 * IN, h2=0.4 * IN)


def draw_continuation_block(g: Group, f: Frame, design: CableDesign, size_letter: str, sheet_no: int, total: int) -> None:
    w = TB_W - TB_LEFT_W
    x, y = f.x1 - w, f.y1 - CONT_TB_H
    g.rect(x, y, w, CONT_TB_H, width=THICK, fill="#ffffff")
    _number_rows(g, x, y, w, design, size_letter, sheet_no, total, h1=0.5 * IN, h2=CONT_TB_H - 0.5 * IN)


def projection_symbol(g: Group, x: float, y: float, h: float) -> None:
    """Third-angle projection symbol: frustum narrowing toward its end view (two circles) on the right."""
    big, small, length = h, h * 0.5, h * 1.1
    g.poly([(x, y - big / 2), (x + length, y - small / 2), (x + length, y + small / 2), (x, y + big / 2)],
           closed=True, width=THIN)
    g.line(x - 3, y, x + length + 3, y, width=THIN, dash=(6, 1.5, 1.5, 1.5))
    cx = x + length + h * 0.45 + big / 2
    g.circle(cx, y, big / 2, width=THIN)
    g.circle(cx, y, small / 2, width=THIN)
    g.line(cx - big / 2 - 3, y, cx + big / 2 + 3, y, width=THIN, dash=(6, 1.5, 1.5, 1.5))
    g.line(cx, y - big / 2 - 3, cx, y + big / 2 + 3, width=THIN, dash=(6, 1.5, 1.5, 1.5))


def draw_tolerance_block(g: Group, f: Frame, design: CableDesign) -> None:
    x, y = f.tb_left - TOL_W, f.tb_top
    g.rect(x, y, TOL_W, TB_H, width=THICK, fill="#ffffff")
    units = UNIT_NAMES.get(design.units.upper(), design.units)
    ly = y + BODY_FONT + 4
    for line in DEFAULT_TOLERANCE_LINES:
        line = line.replace("{UNITS_NAME}", units).replace("{TOL}", design.tolerance)
        g.text(x + 6, ly, fit_text(line, BODY_FONT, TOL_W - 12), size=BODY_FONT, bold=line.endswith(":"))
        ly += BODY_FONT + 3
    g.line(x, y + TB_H - 0.55 * IN, x + TOL_W, y + TB_H - 0.55 * IN, width=THIN)
    g.text(x + 4, y + TB_H - 0.55 * IN + HEADING_FONT, "THIRD ANGLE PROJECTION", size=HEADING_FONT, role="heading")
    projection_symbol(g, x + TOL_W / 2 - 0.35 * IN, y + TB_H - 0.2 * IN, 0.2 * IN)


def draw_application_block(g: Group, f: Frame, design: CableDesign) -> None:
    tb = design.title_block
    x, y = f.tb_left - TOL_W - APP_W, f.tb_top
    g.rect(x, y, APP_W, TB_H, width=THICK, fill="#ffffff")
    g.rect(x, y, APP_W, 0.25 * IN, width=THIN)
    g.text(x + APP_W / 2, y + 0.25 * IN - 5, "APPLICATION", size=HEADING_FONT, anchor="middle", role="heading")
    half = APP_W / 2
    _cell(g, x, y + 0.25 * IN, half, 0.6 * IN, "NEXT ASSY", tb.next_assy)
    _cell(g, x + half, y + 0.25 * IN, half, 0.6 * IN, "USED ON", tb.used_on)
    if tb.statement:
        sy = y + 0.85 * IN + BODY_FONT + 2
        for line in _wrap_fit(tb.statement.upper(), BODY_FONT * 0.83, APP_W - 10, 5):
            g.text(x + 5, sy, line, size=HEADING_FONT, role="heading")
            sy += HEADING_FONT + 2


def draw_revision_block(g: Group, f: Frame, design: CableDesign) -> float:
    """ASME Y14.35 revision block at the top right of sheet 1. Returns its bottom y."""
    revs = design.revisions or [type("R", (), dict(zone="", rev=current_rev(design), description="INITIAL RELEASE",
                                                   date=design.title_block.date,
                                                   approved=design.title_block.approved_by))()]
    cols = [("ZONE", 0.6), ("REV", 0.5), ("DESCRIPTION", 2.7), ("DATE", 1.0), ("APPROVED", 1.2)]
    x0, y = f.x1 - REV_W, f.y0
    row_h = BODY_FONT + 8
    g.rect(x0, y, REV_W, row_h, width=THICK, fill="#ffffff")
    g.text(x0 + REV_W / 2, y + row_h - 6, "REVISIONS", size=BODY_FONT, bold=True, anchor="middle")
    y += row_h
    x = x0
    for name, w in cols:
        _cell(g, x, y, w * IN, row_h, "", name, size=HEADING_FONT, center=True, role="heading")
        x += w * IN
    y += row_h
    for r in revs:
        x = x0
        for (name, w), val in zip(cols, (r.zone, r.rev, r.description, r.date, r.approved)):
            _cell(g, x, y, w * IN, row_h, "", str(val or ""), center=name != "DESCRIPTION")
            x += w * IN
        y += row_h
    g.rect(x0, f.y0, REV_W, y - f.y0, width=THICK)
    return y


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
ROW_H, HEADER_H, TITLE_H = 12.5, 14.0, 16.0


def table_widths(headers: list[str], rows: list[list[str]], size: float = T, caps: list[float] | None = None) -> list[float]:
    widths = []
    for j, h in enumerate(headers):
        w = max([text_width(h, size, True)] + [text_width(r[j], size) for r in rows]) + 8
        if caps and caps[j]:
            w = min(w, caps[j])
        widths.append(max(w, 20))
    return widths


def flag_symbol(g: Group, cx: float, cy: float, number: int | str, size: float = T) -> None:
    """Flag note symbol (Y14.100): the note number inside an equilateral triangle."""
    s = size * 1.9
    h = s * math.sqrt(3) / 2
    g.poly([(cx, cy - h * 0.62), (cx + s / 2, cy + h * 0.38), (cx - s / 2, cy + h * 0.38)], closed=True,
           width=THIN, fill="#ffffff")
    g.text(cx, cy + h * 0.3, str(number), size=size, bold=True, anchor="middle")


def draw_table(g: Group, x: float, y: float, headers: list[str], rows: list[list[str]], widths: list[float],
               title: str = "", size: float = T, center_cols: frozenset[int] = frozenset(),
               flag_cols: frozenset[int] = frozenset(), upward: bool = False) -> float:
    """Ruled table with its top-left at (x, y). Returns its height.

    ``upward`` draws a Y14.34 parts list: title at the bottom, column headings above it, and rows reading upward.
    """
    total_w = sum(widths)
    n = len(rows)
    height = (TITLE_H if title else 0) + HEADER_H + n * ROW_H
    if upward:
        title_y = y + n * ROW_H + HEADER_H
        header_y = y + n * ROW_H
        row_y = [y + (n - 1 - i) * ROW_H for i in range(n)]
        body_top, body_bottom = y, y + n * ROW_H + HEADER_H
    else:
        title_y = y
        header_y = y + (TITLE_H if title else 0)
        row_y = [header_y + HEADER_H + i * ROW_H for i in range(n)]
        body_top, body_bottom = header_y, header_y + HEADER_H + n * ROW_H
    if title:
        if upward:
            g.rect(x, title_y, total_w, TITLE_H, width=THIN)
            g.text(x + total_w / 2, title_y + TITLE_H - 4.5, title, size=size, bold=True, anchor="middle")
        else:
            g.text(x, title_y + TITLE_H - 4.5, title, size=size, bold=True)
    g.rect(x, header_y, total_w, HEADER_H, fill=HEADER_FILL, width=THIN)
    cx = x
    for h, w in zip(headers, widths):
        g.text(cx + w / 2, header_y + HEADER_H - 4, fit_text(h, size, w - 4, True), size=size, bold=True, anchor="middle")
        cx += w
    for row, ry in zip(rows, row_y):
        cx = x
        for j, (val, w) in enumerate(zip(row, widths)):
            if j in flag_cols and val:
                for k, num in enumerate(val.split()):
                    flag_symbol(g, cx + 11 + k * 16, ry + ROW_H / 2 + 0.5, num, size)
            else:
                val = fit_text(val, size, w - 6)
                if j in center_cols:
                    g.text(cx + w / 2, ry + ROW_H - 3.5, val, size=size, anchor="middle")
                else:
                    g.text(cx + 3, ry + ROW_H - 3.5, val, size=size)
            cx += w
        g.line(x, ry + ROW_H, x + total_w, ry + ROW_H, width=THIN)
    g.rect(x, body_top, total_w, body_bottom - body_top, width=THIN)
    cx = x
    for w in widths[:-1]:
        cx += w
        g.line(cx, body_top, cx, body_bottom, width=THIN)
    return height


# ---------------------------------------------------------------------------
# Connector side assignment (shared by the assembly view and wiring diagram)
# ---------------------------------------------------------------------------
def assign_sides(design: CableDesign) -> tuple[list[ConnectorEnd], list[ConnectorEnd]]:
    """Split connectors into a left and right column so most wires cross the cable. The datum connector comes first
    (top left)."""
    conns = list(design.connectors)
    if not conns:
        return [], []
    datum = design.datum_ref()
    conns.sort(key=lambda c: c.ref != datum)
    left, right = [conns[0]], []
    for c in conns[1:]:
        to_left = to_right = 0
        for w in design.wires:
            ends = {w.from_ref, w.to_ref}
            if c.ref in ends:
                other = (ends - {c.ref}) or {c.ref}
                to_left += sum(1 for o in left if o.ref in other)
                to_right += sum(1 for o in right if o.ref in other)
        if to_left > to_right or (to_left == to_right and len(right) <= len(left)):
            right.append(c)
        else:
            left.append(c)
    return left, right


# ---------------------------------------------------------------------------
# Assembly view
# ---------------------------------------------------------------------------
BALLOON_R = 9.0
BALLOON_OFF = 66.0
DIM_OFF = 76.0
SPLICE_DIM_OFF = 46.0
LEG_SPACING = 240.0
CABLE_W = 14.0
LABEL_GAP = 16.0
PINOUT_TOP = 100.0      # pinout views start this far below their connector's centreline


@dataclass
class _Marks:
    """Find numbers ballooned and flag notes to place next to them."""
    flags: dict[int, int] = field(default_factory=dict)       # find number -> flag note number
    ballooned: set[int] = field(default_factory=set)


def balloon(g: Group, x: float, y: float, item: int, marks: _Marks, anchor: tuple[float, float] | None = None,
            flag_dir: int = 1) -> None:
    g.circle(x, y, BALLOON_R, fill="#ffffff", width=THIN)
    g.text(x, y + 2.5, str(item), size=T, anchor="middle", bold=True)
    marks.ballooned.add(item)
    if anchor:
        ax, ay = anchor
        d = math.hypot(ax - x, ay - y) or 1
        g.line(x + (ax - x) / d * BALLOON_R, y + (ay - y) / d * BALLOON_R, ax, ay, width=THIN)
        g.circle(ax, ay, 1.4, fill="#000000", width=THIN)
    if item in marks.flags:
        flag_symbol(g, x + flag_dir * (BALLOON_R + 9), y, marks.flags[item])


def end_length(c: ConnectorEnd) -> float:
    a = 104.0 if c.backshell_pn else 56.0
    if c.heatshrink_pn:
        a = a - (22 if c.backshell_pn else 6) + 60
    if c.label_pn:
        a += LABEL_GAP + 58
    return a


def draw_connector_end(g: Group, x_face: float, y: float, d: int, c: ConnectorEnd, items: dict[str, int],
                       balloon_side: int, marks: _Marks) -> None:
    """Draw a connector end with its mating face at x_face; the cable leaves in direction d (+1 right, -1 left)."""
    f = lambda a: x_face + d * a  # noqa: E731
    span = lambda a0, a1: (min(f(a0), f(a1)), abs(a1 - a0))  # noqa: E731
    anchors: list[tuple[str, float, float]] = []  # (pn, x, half-height)

    x, w = span(0, 18)
    g.rect(x, y - 31, w, 62, fill="#ffffff", width=THICK)
    for a in (4.5, 9, 13.5):
        g.line(f(a), y - 31, f(a), y + 31, width=THIN)
    x, w = span(18, 56)
    g.rect(x, y - 26, w, 52, fill="#ffffff", width=THICK)
    g.text(f(37), y + 4, fit_text(c.ref, 11, 34, True), size=11, bold=True, anchor="middle")
    anchors.append((c.connector_pn, f(37), 26))
    a = 56.0
    if c.backshell_pn:
        g.poly([(f(56), y - 21), (f(104), y - 10), (f(104), y + 10), (f(56), y + 21)], closed=True, fill="#ffffff", width=THICK)
        g.line(f(64), y - 19.3, f(64), y + 19.3, width=THIN)
        anchors.append((c.backshell_pn, f(70), 18))
        a = 104.0
    if c.heatshrink_pn:
        start = a - (22 if c.backshell_pn else 6)
        x, w = span(start, start + 60)
        g.rect(x, y - 13, w, 26, fill=SHADE, width=THICK)
        anchors.append((c.heatshrink_pn, f(start + 36), 13))
        a = start + 60
    if c.label_pn:
        start = a + LABEL_GAP
        x, w = span(start, start + 58)
        g.rect(x, y - 10, w, 20, fill="#ffffff", width=THICK)
        g.text(f(start + 29), y + 2.5, fit_text(c.legend, T, 54, True), size=T, bold=True, anchor="middle")
        anchors.append((c.label_pn, f(start + 29), 10))

    s = balloon_side
    for pn, ax, half in anchors:
        if pn in items:
            balloon(g, ax, y + s * BALLOON_OFF, items[pn], marks, (ax, y + s * half), flag_dir=d)
    if c.description:   # wrapped into a narrow column outboard of the mating face
        lines = wrap(c.description.upper(), T, 64)[:4]
        for i, line in enumerate(lines):
            g.text(f(-6), y + 3 + (i - (len(lines) - 1) / 2) * (T + 2), line, size=T, anchor="end" if d == 1 else "start")


def datum_symbol(g: Group, x: float, y: float, d: int, letter: str) -> None:
    """ASME Y14.5 datum feature symbol: filled triangle on the extension line at (x, y), leader and framed letter
    in direction d."""
    g.poly([(x, y - 4), (x, y + 4), (x + d * 7, y)], closed=True, fill="#000000", width=THIN)
    g.line(x + d * 7, y, x + d * 14, y, width=THIN)
    bx = x + d * 14 + (0 if d == 1 else -16)
    g.rect(bx, y - 8, 16, 16, fill="#ffffff", width=THIN)
    g.text(bx + 8, y + 3, letter, size=T, bold=True, anchor="middle")


def splice_location(design: CableDesign, sp) -> tuple[float | None, str]:
    """Location of a splice per IPC-D-620: (distance, reference). Measured from DATUM A along the datum leg and along a
    two-connector cable; from the harness centerline at the breakout on a branch. None if a needed length is unknown."""
    datum = design.datum_ref()
    if sp.distance is None or not sp.near:
        return None, ""
    datum_ref = f"DATUM A ({datum} FACE)"
    if sp.near == datum:
        return sp.distance, datum_ref
    if len(design.connectors) == 2:
        total = design.end_to_end_length()
        return (total - sp.distance if total is not None else None), datum_ref
    leg = design.leg_length(sp.near)
    return (leg - sp.distance if leg is not None else None), f"BREAKOUT CENTERLINE (TOWARD {sp.near})"


def break_symbol(g: Group, x: float, y: float) -> None:
    g.rect(x - 4, y - CABLE_W / 2 - 2, 8, CABLE_W + 4, fill="#ffffff", stroke=None)
    for dx in (-4, 4):
        g.line(x + dx - 3, y + CABLE_W / 2 + 3, x + dx + 3, y - CABLE_W / 2 - 3, width=THICK)


def dimension(g: Group, xa: float, xb: float, y: float, ext_a: float, ext_b: float, label: str) -> None:
    """Horizontal dimension (Y14.5): visible gap at the object, extension 3 beyond the dimension line, 3:1 arrows."""
    s = 1 if y > ext_a else -1
    g.line(xa, ext_a, xa, y + s * 4, width=THIN)
    g.line(xb, ext_b, xb, y + s * 4, width=THIN)
    lo, hi = min(xa, xb), max(xa, xb)
    g.line(lo, y, hi, y, width=THIN)
    g.arrow(lo, y, hi, y)
    g.arrow(hi, y, lo, y)
    tw = text_width(label, 8, True)
    g.rect((lo + hi) / 2 - tw / 2 - 3, y - 6, tw + 6, 11, fill="#ffffff", stroke=None)
    g.text((lo + hi) / 2, y + 3, label, size=8, bold=True, anchor="middle")


def _dim_text(value: float | None, design: CableDesign, ref: bool = False) -> str:
    if value is None:
        return "TBD"
    return f"{fmt_length(value)}{' REF' if ref else ''}"


def assembly_view(design: CableDesign, items: dict[str, int], marks: _Marks | None = None) -> Group:
    marks = marks or _Marks()
    g = Group(layer="ASSEMBLY")
    left, right = assign_sides(design)
    if not left:
        g.text(0, 0, "NO CONNECTORS DEFINED", size=12, bold=True)
        return g
    located = {sp.ref for sp in design.splices if sp.near and sp.distance is not None and design.connector(sp.near)}
    used_splices = [sp for sp in design.splices if any(sp.ref in (w.from_ref, w.to_ref) for w in design.wires)]
    bundle_pns = [p for w in design.wires for p in (w.wire_pn, w.label_pn, w.heatshrink_pn)]
    bundle_pns += [p for gr in design.groups if design.group_members(gr.group_id)
                   for p in (gr.cable_pn, gr.shield_pn, gr.shield_term_pn)]
    bundle_pns += [sp.splice_pn for sp in used_splices if sp.ref not in located]
    wire_items = sorted({items[p] for p in bundle_pns if p in items})
    straight = len(left) == 1 and len(right) == 1

    # Pinout of each connector, drawn under it; legs are spread apart to make room
    views = {c.ref: v for c in design.connectors
             if (v := face_view(c.ref, c.connector_pn, set(design.pins_used(c.ref)), T)) is not None}
    view_h = max([v.bounds()[3] - v.bounds()[1] for v in views.values()], default=0.0)
    spacing = max(LEG_SPACING, PINOUT_TOP + view_h + 110) if views else LEG_SPACING

    per_row = 4
    cable_min = max(110.0, 30 + min(len(wire_items), per_row) * 2 * BALLOON_R + 24)
    if views:      # room between the pinouts of facing connectors
        view_w = max(v.bounds()[2] - v.bounds()[0] for v in views.values())
        cable_min = max(cable_min, view_w / 2 - 60)
    max_dy = max(spacing * (max(len(left), len(right)) - 1) / 2, 0)
    bend = 0.0 if straight else 40 + 0.45 * max_dy
    left_end = max(end_length(c) for c in left)
    right_end = max((end_length(c) for c in right), default=0)
    bx, by = left_end + cable_min + bend, 0.0
    right_face = bx + bend + cable_min + right_end

    legs = []  # (connector, face_x, y, d)
    for side, face, d in ((left, 0.0, 1), (right, right_face, -1)):
        for i, c in enumerate(side):
            legs.append((c, face, by + (i - (len(side) - 1) / 2) * spacing, d))

    paths = []
    for c, face, y, d in legs:
        # The cable runs into the connector body; the backshell, boot and label are drawn over it
        start = face + d * 40
        paths.append([(start, y), (bx - d * bend, y), (bx, by)])
    if not right:
        paths.append([(bx, by), (bx + 30, by)])
    for p in paths:
        g.poly(p, width=CABLE_W, round_joins=True)
    for p in paths:
        g.poly(p, width=CABLE_W - 2.5, stroke="#ffffff", round_joins=True)
    if right and not straight:
        g.circle(bx, by, 10, fill=SHADE, width=THICK)
        g.text(bx + 14, by + 3, "BREAKOUT", size=T, bold=True)
    if not right:
        for k in (-6, -2, 2, 6):
            g.line(bx + 37, by + k * 0.8, bx + 52, by + k * 1.6, width=THICK)
        g.text(bx + 58, by + 3, "WIRE ENDS PER WIRE LIST", size=T, bold=True)

    for idx, (c, face, y, d) in enumerate(legs):
        run_start = face + d * end_length(c)
        run_end = bx - d * bend
        dim_side = 1 if straight else (-1 if y < by - 1 else 1)
        bal_side = -dim_side
        break_symbol(g, run_start + (run_end - run_start) * 0.85, y)
        draw_connector_end(g, face, y, d, c, items, bal_side, marks)
        if idx == 0 and wire_items:
            x0 = run_start + d * 30
            y0 = y + bal_side * BALLOON_OFF * 0.75
            balloon(g, x0, y0, wire_items[0], marks, (x0 - d * 12, y + bal_side * CABLE_W / 2))
            for k, item in enumerate(wire_items[1:], start=1):
                balloon(g, x0 + d * (k % per_row) * 2 * BALLOON_R,
                        y0 + bal_side * (k // per_row) * 2 * BALLOON_R, item, marks, flag_dir=d)

    # Splices: marker on the leg, find number, and a dimension per IPC-D-620: from DATUM A on the datum leg (and
    # along a two-connector cable), from the harness centerline at the breakout on a branch
    leg_of = {c.ref: (face, y, d, c) for c, face, y, d in legs}
    datum = design.datum_ref()
    for sp in used_splices:
        if sp.ref not in located or sp.near not in leg_of:
            continue
        face, y, d, c = leg_of[sp.near]
        run_start, run_end = face + d * end_length(c), bx - d * bend
        leg_len = c.length if c.length else design.end_to_end_length()
        frac = min(max((sp.distance / leg_len) if leg_len else 0.5, 0.15), 0.7)
        if straight and leg_len and design.end_to_end_length():
            frac = min(max(sp.distance / design.end_to_end_length() * 2, 0.15), 0.7)
        x = run_start + (run_end - run_start) * frac
        g.rect(x - 8, y - CABLE_W / 2 - 3, 16, CABLE_W + 6, fill=SHADE, width=THICK)
        dim_side = 1 if (straight or y >= by - 1) else -1
        side = -dim_side
        by_ = y + side * 34
        if sp.splice_pn in items:
            balloon(g, x, by_, items[sp.splice_pn], marks, (x, y + side * (CABLE_W / 2 + 3)))
        g.text(x + d * 14 if sp.splice_pn in items else x, by_ + 3 + (0 if sp.splice_pn in items else 0), sp.ref,
               size=T, bold=True, anchor="start" if d == 1 else "end")
        value, _ref = splice_location(design, sp)
        if straight or sp.near == datum:
            dface = leg_of[datum][0]
            dimension(g, dface, x, y + dim_side * SPLICE_DIM_OFF, y + dim_side * 34, y + dim_side * (CABLE_W / 2 + 5),
                      _dim_text(value, design))
        else:
            dimension(g, bx, x, y + dim_side * SPLICE_DIM_OFF, by + dim_side * 12, y + dim_side * (CABLE_W / 2 + 5),
                      _dim_text(value, design))

    if straight:
        (_, fa, ya, _), (_, fb, yb, _) = legs
        dimension(g, fa, fb, ya + DIM_OFF, ya + 34, yb + 34, _dim_text(design.end_to_end_length(), design))
    else:
        for c, face, y, d in legs:
            s = -1 if y < by - 1 else 1
            dimension(g, face, bx, y + s * DIM_OFF, y + s * 34, by + s * 12, _dim_text(c.length, design))

    # DATUM A: the datum connector's face (IPC-D-620), on its extension line
    face, y, d, _c = leg_of[datum]
    s = 1 if (straight or y >= by - 1) else -1
    datum_symbol(g, face, y + s * 58, -d, "A")

    for c, face, y, d in legs:
        v = views.get(c.ref)
        if v is None:
            continue
        vx0, vy0, vx1, vy1 = v.bounds()
        v.dx, v.dy = face + d * 28 - (vx0 + vx1) / 2, y + PINOUT_TOP - vy0
        g.add(v)
    return g


# ---------------------------------------------------------------------------
# Wiring diagram (ASME Y14.15 style)
# ---------------------------------------------------------------------------
def _gauge_text(g: str) -> str:
    return f"{g} AWG" if g and g.replace(".", "").isdigit() else g


def wire_tag(w: Wire) -> str:
    return "  ".join(x for x in (w.wire_id, _gauge_text(w.gauge), w.color.upper()) if x)


NC = "NC"
NC_ROWS_MAX = 24        # more unused positions than this are summarised in one row (and listed in the notes)


@dataclass
class _Row:
    pin: str
    signal: str
    wire: Wire | None = None
    end_no: int = 0
    shield_of: str = ""
    shell: bool = False           # a shield termination row: SHELL (connector shell) or ADPTR (backshell/adapter)

    @property
    def key(self) -> str:
        """Lookup key of the row: its pin, or a per-shield key for a SHELL/ADPTR row (there can be several)."""
        return f"#{self.pin}:{self.shield_of}" if self.shell else self.pin


NEST_STEP = 22.0       # extra offset per nesting level, so an overall shield sits clear of the shields inside it
CAPSULE_W = 12.0       # width of a shield / cable capsule


def _capsule(g: Group, cx: float, top: float, bot: float, w: float, dashed: bool) -> None:
    """A capsule (rounded bar) from ``top`` to ``bot``: how a shield (dashed) or a cable jacket is drawn."""
    r = w / 2
    pts = [(cx + r * math.cos(math.pi + math.pi * k / 8), top + r + r * math.sin(math.pi + math.pi * k / 8))
           for k in range(9)]
    pts += [(cx + r * math.cos(math.pi * k / 8), bot - r + r * math.sin(math.pi * k / 8)) for k in range(9)]
    g.poly(pts, closed=True, width=THIN, dash=(2.5, 1.5) if dashed else None)


def _shield_columns(design: CableDesign, ref: str, rows: list) -> dict[str, int]:
    """Column of each group's capsules at connector ``ref`` (0 = nearest the connector). A group whose rows (and drain
    lead) overlap another's vertically gets its own column, and a shield always sits outside every group inside it,
    so capsules, joining lines and leads never run over each other."""
    spans: dict[str, tuple[int, int]] = {}
    gapped: dict[str, bool] = {}
    for gr in design.groups:
        gid = gr.group_id
        member_ids = {w.wire_id for w in design.group_members(gid)}
        idx = [i for i, row in enumerate(rows)
               if (row.wire is not None and row.wire.wire_id in member_ids)
               or (row.shield_of and gid in design.group_chain(row.shield_of))]
        kind, pin = parse_shield_term(design.shield_term_at(gr, ref), ref)
        if idx and kind == "PIN":     # the drain lead runs down (or up) the column to its pin's row
            idx += [i for i, row in enumerate(rows) if row.pin == pin and row.wire is None]
        if idx and (gr.shielded or gr.jacketed or gr.twisted):
            spans[gid] = (min(idx), max(idx))
            gapped[gid] = max(idx) - min(idx) + 1 > len(idx)
    cols: dict[str, int] = {}
    used: dict[int, list[tuple[int, int]]] = {}
    # compact groups nearest the connector; a group split over non-adjacent rows further out, so its joining line
    # doesn't cross the others' leads
    for gid in sorted(spans, key=lambda g: (design.group_level(g), gapped[g], spans[g])):
        lo, hi = spans[gid]
        inner = [cols[k] for k in cols if k != gid and gid in design.group_chain(k)]
        col = max(inner) + 1 if inner else 0
        while any(not (hi < a or lo > b) for a, b in used.get(col, [])):
            col += 1
        cols[gid] = col
        used.setdefault(col, []).append((lo, hi))
    return cols


def _shell_rows(design: CableDesign, ref: str, rows: list) -> list:
    """``rows`` with a SHELL (or ADPTR, for a backshell) row for each shield terminated to ``ref``'s shell, placed
    right under the shield's own rows; inner shields first, so an overall shield's row comes after theirs."""
    label = "ADPTR" if design.shell_name(ref) == "BACKSHELL" else "SHELL"
    out = list(rows)
    for gr in sorted(design.shell_terminations(ref), key=lambda g: design.group_level(g.group_id)):
        gid = gr.group_id
        member_ids = {w.wire_id for w in design.group_members(gid)}
        last = -1
        for i, row in enumerate(out):
            if (row.wire is not None and row.wire.wire_id in member_ids) or \
                    (row.shield_of and gid in design.group_chain(row.shield_of)):
                last = i
        out.insert(last + 1 if last >= 0 else len(out), _Row(label, f"{gid} SHIELD", shield_of=gid, shell=True))
    return out


def _member_runs(pins: set[str], ref: str, row_index: dict, row_y: dict, inside=lambda row: False) -> list[list[float]]:
    """Row centres of a group's pins at one connector, split into runs of neighbouring rows. A row that carries some
    other wire (or another group's shield drain) between two members splits the run; empty (NC) rows and rows
    ``inside`` the group (e.g. the drain of a pair under this shield) don't."""
    idx = sorted(row_index[(ref, p)][0] for p in pins)
    rows = row_index[(ref, next(iter(pins)))][1]
    runs: list[list[float]] = []
    prev = None
    for i in idx:
        between = rows[prev + 1:i] if prev is not None else []
        if prev is None or any((r.wire is not None or r.shield_of) and not inside(r) for r in between):
            runs.append([])
        runs[-1].append(row_y[(ref, rows[i].pin)])
        prev = i
    return runs


def wiring_diagram(design: CableDesign) -> Group:
    g = Group(layer="WIRING")
    shields = Group(layer="SHIELDS")
    left, right = assign_sides(design)
    side_of = {c.ref: 1 for c in left} | {c.ref: -1 for c in right}
    has_groups = any(design.group_members(gr.group_id) for gr in design.groups)

    rows: dict[str, list[_Row]] = {c.ref: [] for c in design.connectors}
    for w in design.wires:
        for end_no, (ref, pin) in enumerate(((w.from_ref, w.from_pin), (w.to_ref, w.to_pin))):
            if ref in rows:
                rows[ref].append(_Row(pin, w.signal, w, end_no))
    for c in design.connectors:
        for gr, pin in design.shield_pins(c.ref):
            if not any(r.pin == pin for r in rows[c.ref]):
                rows[c.ref].append(_Row(pin, f"{gr.group_id} SHIELD", None, 0, gr.group_id))
    # rows in the connector's pin order (set on the canvas), else natural order
    for ref, lst in rows.items():
        key = design.pin_sort_key(ref)
        lst.sort(key=lambda r: (key(r.pin), natural_key(r.wire.wire_id if r.wire else "")))
    # Unused contact positions: one NC row each, or a single summary row when there are many
    for c in design.connectors:
        nc = design.unused_pins(c.ref)
        if 0 < len(nc) <= NC_ROWS_MAX:
            key = design.pin_sort_key(c.ref)
            rows[c.ref] = sorted(rows[c.ref] + [_Row(p, NC) for p in nc], key=lambda r: key(r.pin))
        elif nc:
            rows[c.ref].append(_Row(NC, f"{len(nc)} POSITIONS, SEE NOTES"))
    # Shields terminated to the shell: a SHELL / ADPTR row under each one's wires (IPC/WHMA-A-620 style)
    for c in design.connectors:
        rows[c.ref] = _shell_rows(design, c.ref, rows[c.ref])

    size, row_h = T, 14.0
    tag_end = max([60.0] + [text_width(wire_tag(w), T) + 10 for w in design.wires])
    columns = {c.ref: _shield_columns(design, c.ref, rows[c.ref]) for c in design.connectors}
    n_cols = max([max(cols.values(), default=0) for cols in columns.values()], default=0)
    stub = max(90.0, tag_end + (40 + NEST_STEP * n_cols if has_groups else 8))
    oval_off = tag_end + 13

    def table_dims(c: ConnectorEnd):
        rs = rows.get(c.ref, [])
        pin_w = max([30.0] + [text_width(r.pin, size, True) + 12 for r in rs])
        sig_w = min(170.0, max([80.0] + [text_width(r.signal, size) + 12 for r in rs]))
        head_h = 18 + 10 * sum(1 for x in (c.connector_pn, c.description) if x)
        return pin_w, sig_w, head_h, max(len(rs), 1)

    tw_left = max([sum(table_dims(c)[:2]) for c in left] + [0])
    same = {d: [w for w in design.wires if side_of.get(w.from_ref) == d and side_of.get(w.to_ref) == d] for d in (1, -1)}
    used_splices = [sp for sp in design.splices if any(sp.ref in (w.from_ref, w.to_ref) for w in design.wires)]
    center = max(180 + 6 * (len(same[1]) + len(same[-1])), 240 if used_splices else 0)
    x_left_anchor = tw_left + stub
    x_right_table = tw_left + 2 * stub + center
    x_right_anchor = x_right_table - stub

    anchor: dict[tuple[int, int], tuple[float, float]] = {}
    row_y: dict[tuple[str, str], float] = {}
    row_index: dict[tuple[str, str], tuple[int, list]] = {}
    edges: dict[str, tuple[float, int]] = {}
    for side, d in ((left, 1), (right, -1)):
        y = 0.0
        for c in side:
            pin_w, sig_w, head_h, nrows = table_dims(c)
            tw = pin_w + sig_w
            x = tw_left - tw if d == 1 else x_right_table
            g.rect(x, y, tw, head_h, fill=HEADER_FILL, width=THICK)
            g.text(x + tw / 2, y + 13, c.ref, size=10, bold=True, anchor="middle")
            ty = y + 13
            for line in (c.connector_pn, c.description.upper()):
                if line:
                    ty += 10
                    g.text(x + tw / 2, ty, fit_text(line, T, tw - 6), size=T, anchor="middle")
            y += head_h
            g.rect(x, y, tw, 12, fill="#ffffff", width=THIN)
            pin_x, sig_x = (x, x + pin_w) if d == 1 else (x + sig_w, x)
            g.text(pin_x + pin_w / 2, y + 9, "PIN", size=T, bold=True, anchor="middle")
            g.text(sig_x + sig_w / 2, y + 9, "SIGNAL", size=T, bold=True, anchor="middle")
            y += 12
            rs = rows.get(c.ref, [])
            g.rect(x, y, tw, nrows * row_h, width=THICK)
            div = x + (pin_w if d == 1 else sig_w)
            g.line(div, y - 12, div, y + nrows * row_h, width=THIN)
            if not rs:
                g.text(x + tw / 2, y + 10, "NO WIRES", size=size, anchor="middle")
            edge = x + tw if d == 1 else x
            edges[c.ref] = (edge, d)
            for r, row in enumerate(rs):
                ry = y + r * row_h
                row_index[(c.ref, row.key)] = (r, rs)
                if r:
                    g.line(x, ry, x + tw, ry, width=THIN)
                g.text(pin_x + pin_w / 2, ry + 10, row.pin, size=size, bold=True, anchor="middle")
                g.text(sig_x + 4, ry + 10, fit_text(row.signal, size, sig_w - 8), size=size)
                cy = ry + row_h / 2
                row_y.setdefault((c.ref, row.key), cy)
                if row.wire is None and not row.shield_of:      # NC: no connection drawn
                    continue
                g.circle(edge, cy, 1.3, fill="#000000", width=THIN)
                if row.wire is None:        # shield drain or SHELL/ADPTR row: the shield's lead comes in here
                    continue
                tip = edge + d * stub
                g.line(edge, cy, tip, cy, width=THIN)
                g.text(edge + d * 5, cy - 2.5, wire_tag(row.wire), size=T, anchor="start" if d == 1 else "end")
                anchor[(id(row.wire), row.end_no)] = (tip, cy)
            y += nrows * row_h + 28

    node: dict[str, tuple[float, float]] = {}
    sx = (x_left_anchor + x_right_anchor) / 2
    wanted = []
    for sp in used_splices:
        ys = [anchor[(id(w), 1 - e)][1] for w in design.wires for e, ref in enumerate((w.from_ref, w.to_ref))
              if ref == sp.ref and (id(w), 1 - e) in anchor]
        wanted.append((sum(ys) / len(ys) if ys else 0.0, sp))
    last = -1e9
    for want, sp in sorted(wanted, key=lambda t: t[0]):
        yy = max(want, last + 32)
        node[sp.ref] = (sx, yy)
        last = yy

    lane = {1: 0, -1: 0}
    for w in design.wires:
        ends = []
        for e, ref in enumerate((w.from_ref, w.to_ref)):
            if ref in node:
                ends.append(node[ref])
            elif (id(w), e) in anchor:
                ends.append(anchor[(id(w), e)])
        if len(ends) != 2:
            continue
        a, b = ends
        sa, sb = side_of.get(w.from_ref), side_of.get(w.to_ref)
        if sa is not None and sa == sb:
            lx = (x_left_anchor + 12 + 6 * lane[1]) if sa == 1 else (x_right_anchor - 12 - 6 * lane[-1])
            lane[sa] += 1
            g.poly([a, (lx, a[1]), (lx, b[1]), b], width=THIN)
        else:
            g.line(a[0], a[1], b[0], b[1], width=THIN)

    for sp in used_splices:
        x, y = node[sp.ref]
        g.circle(x, y, 3.5, fill="#000000", width=THIN)
        g.text(x, y - 7, sp.ref, size=8, bold=True, anchor="middle")
        if sp.splice_pn:
            g.text(x, y + 14, sp.splice_pn, size=T, anchor="middle")

    tied = False
    for gr in design.groups:
        members = design.group_members(gr.group_id)
        if not members:
            continue
        shielded = gr.shielded or "SHIELD" in gr.kind.upper()
        if not (shielded or gr.jacketed or gr.twisted):
            continue
        gid = gr.group_id
        level = design.group_level(gid)
        for ref, (edge, d) in edges.items():
            pins = {p for w in members for r, p in ((w.from_ref, w.from_pin), (w.to_ref, w.to_pin))
                    if r == ref and (ref, p) in row_y}
            if not pins:
                continue
            # inner shields close to the connector, each enclosing shield a column further out, so none overlap
            ox = edge + d * (oval_off + NEST_STEP * columns.get(ref, {}).get(gid, level))
            runs = _member_runs(pins, ref, row_index, row_y,
                                lambda row, gid=gid: bool(row.shield_of) and gid in design.group_chain(row.shield_of))
            spans = []
            for ys in runs:
                top, bot = ys[0] - 6 - 2 * level, ys[-1] + 6 + 2 * level
                spans.append((top, bot))
                if gr.twisted and len(ys) >= 2:
                    for y1, y2 in zip(ys, ys[1:]):
                        shields.line(ox - 3.5, y1, ox + 3.5, y2, width=THIN)
                        shields.line(ox - 3.5, y2, ox + 3.5, y1, width=THIN)
                if shielded or gr.jacketed:
                    _capsule(shields, ox, top, bot, CAPSULE_W, dashed=shielded)
            # one shield over wires that aren't neighbours: its capsules are joined in the same column
            for (_t1, b1), (t2, _b2) in zip(spans, spans[1:]):
                tied = True
                shields.line(ox, b1, ox, t2, width=THIN, dash=(2.5, 1.5))
            shields.text(ox, spans[0][0] - 2.5, gid, size=T, bold=True, anchor="middle")
            if not shielded:
                continue
            # drain lead: out of the capsule, along its column, into the termination row
            kind, pin = parse_shield_term(design.shield_term_at(gr, ref), ref)
            target = None
            if kind == SHIELD_BACKSHELL:
                target = row_y.get((ref, f"#{'ADPTR' if design.shell_name(ref) == 'BACKSHELL' else 'SHELL'}:{gid}"))
            elif kind == "PIN":
                target = row_y.get((ref, pin))
            top, bot = spans[0][0], spans[-1][1]
            if target is not None:
                start = bot if target >= (top + bot) / 2 else top
                shields.poly([(ox, start), (ox, target), (edge + d * 3, target)], width=THIN, dash=(2.5, 1.5))
            elif kind == SHIELD_FLOAT:
                shields.line(ox, bot, ox, bot + 5, width=THIN, dash=(2.5, 1.5))
                shields.line(ox - 3.5, bot + 5, ox + 3.5, bot + 5, width=THICK)
            elif kind == "":
                shields.text(ox, bot + 9, "?", size=T, bold=True, anchor="middle")
    g.add(shields)

    if has_groups:
        lg = Group(layer="WIRING")
        lg.text(0, 0, "LEGEND:", size=T, bold=True)
        x = text_width("LEGEND:", T, True) + 10
        lg.line(x, -6, x + 8, 0, width=THIN)
        lg.line(x, 0, x + 8, -6, width=THIN)
        lg.text(x + 12, 0, "TWISTED", size=T)
        x += 12 + text_width("TWISTED", T) + 16
        _capsule(lg, x, -9, 3, 8, dashed=True)
        lg.text(x + 8, 0, "SHIELD", size=T)
        x += 8 + text_width("SHIELD", T) + 16
        _capsule(lg, x, -9, 3, 8, dashed=False)
        lg.text(x + 8, 0, "JACKETED CABLE", size=T)
        x += 8 + text_width("JACKETED CABLE", T) + 16
        lg.text(x, 0, "SHELL / ADPTR = SHIELD TERMINATED TO CONNECTOR SHELL / BACKSHELL (ADAPTER)", size=T)
        x += text_width("SHELL / ADPTR = SHIELD TERMINATED TO CONNECTOR SHELL / BACKSHELL (ADAPTER)", T) + 16
        if tied:
            _capsule(lg, x, -12, -5, 6, dashed=True)
            lg.line(x, -5, x, 0, width=THIN, dash=(2.5, 1.5))
            _capsule(lg, x, 0, 7, 6, dashed=True)
            lg.text(x + 7, 0, "JOINED CAPSULES = ONE SHIELD OVER NON-ADJACENT WIRES", size=T)
            x += 7 + text_width("JOINED CAPSULES = ONE SHIELD OVER NON-ADJACENT WIRES", T) + 16
        lg.text(x, 0, "? = SHIELD TERMINATION NOT SPECIFIED", size=T)
        lg.dx, lg.dy = 0.0, g.bounds()[3] + 18
        g.add(lg)
    return g


# ---------------------------------------------------------------------------
# Notes (Y14.100): general notes, and flag notes tied to find numbers
# ---------------------------------------------------------------------------
def wrap(text: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if text_width(trial, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


@dataclass
class Note:
    text: str
    flag_categories: tuple[str, ...] = ()     # BOM categories this flag note applies to

    @property
    def flagged(self) -> bool:
        return bool(self.flag_categories)


def auto_notes(design: CableDesign, bom: list[BomItem], table_sheets: tuple[int, int], bundles: dict | None = None) -> list[Note]:
    def items(cat: str) -> str:
        nums = [str(b.item) for b in bom if b.category == cat]
        return ("FIND NO. " if len(nums) == 1 else "FIND NOS. ") + ", ".join(nums) if nums else ""

    first, last = table_sheets
    sheets = f"SHEET {first}" if first == last else f"SHEETS {first} THRU {last}"
    tables = ["WIRE LIST"]
    active_groups = [gr for gr in design.groups if design.group_members(gr.group_id)]
    used_splices = [sp for sp in design.splices if any(sp.ref in (w.from_ref, w.to_ref) for w in design.wires)]
    if active_groups:
        tables.append("WIRE GROUPS")
    if used_splices:
        tables.append("SPLICES")
    tables.append("LABEL SCHEDULE")
    datum = design.datum_ref()
    dim_note = Note(f"DIMENSIONS PER IPC-D-620: HARNESS DIMENSIONS, INCLUDING BREAKOUT AND SPLICE LOCATIONS, ARE MEASURED "
                    f"FROM DATUM A, THE {datum} CONNECTOR FACE. HARNESS LENGTH IS MEASURED FROM DATUM A TO THE FINAL "
                    f"TERMINATION. BREAKOUT LENGTHS ARE MEASURED FROM THE APPROXIMATE CENTERLINE OF THE HARNESS AT THE "
                    f"BREAKOUT TO THE FINAL TERMINATION.") if datum else None
    notes = [Note(f"ASSEMBLY VIEW AND CONNECTOR PINOUTS ON SHEET {ASSEMBLY_SHEET}. WIRING DIAGRAM ON SHEET "
                  f"{WIRING_SHEET}. {', '.join(tables[:-1])} AND {tables[-1]} ON {sheets}.")]
    if dim_note:
        notes.append(dim_note)
    supplied = [c for c in design.connectors if design.contacts_included(c.ref) and design.pins_used(c.ref)]
    if supplied:
        finds = sorted({b.item for b in bom if b.category == "connector" and any(b.pn == c.connector_pn for c in supplied)})
        contacts = sorted({design.contact_pn(c.ref) for c in supplied if design.contact_pn(c.ref)})
        label = ("FIND NO. " if len(finds) == 1 else "FIND NOS. ") + ", ".join(map(str, finds))
        notes.append(Note(f"CONTACTS{' (' + ', '.join(contacts) + ')' if contacts else ''} ARE SUPPLIED WITH CONNECTORS "
                          f"({label}); DO NOT ORDER SEPARATELY."))
    if any(layout_for(c.connector_pn) for c in design.connectors):
        notes.append(Note("CONNECTOR PINOUTS SHOW THE FRONT (ENGAGING) FACE OF THE CONNECTOR CALLED OUT: INSERT "
                          "ARRANGEMENT PER MIL-STD-1560, SOCKET INSERTS AS THE MIRROR IMAGE OF THE PIN INSERT. FILLED "
                          "CAVITIES ARE WIRED; OPEN CAVITIES ARE NC. MASTER KEYWAY NOT SHOWN."))
    nc = [(c.ref, design.unused_pins(c.ref)) for c in design.connectors]
    nc = [(ref, pins) for ref, pins in nc if pins]
    if nc:
        parts = [f"{ref}: {', '.join(pins)}" if len(pins) <= 40 else f"{ref}: {len(pins)} POSITIONS NOT IN THE WIRE LIST"
                 for ref, pins in nc]
        notes.append(Note("NC (NO CONNECTION) CONTACT POSITIONS: " + "; ".join(parts) + "."))
    if any(gr.twisted and not gr.cable_pn for gr in active_groups):
        notes.append(Note("TWIST THE WIRES OF EACH TWISTED GROUP TOGETHER OVER THEIR FULL LENGTH (SEE WIRE GROUPS TABLE)."))
    if bundles:
        parts = [f"{ref} {fmt_dia(b.diameter, design)}" for ref, b in bundles.items() if b.diameter]
        if parts:
            notes.append(Note("CALCULATED BUNDLE DIAMETER AT CONNECTORS (REF): " + ", ".join(parts) + "."))
    flagged = [
        ("shield", f"INSTALL OVERALL SHIELD ({items('shield')}) OVER SHIELDED GROUPS PER WIRE GROUPS TABLE."),
        ("shield_term", f"TERMINATE SHIELDS PER WIRE GROUPS TABLE USING {items('shield_term')}. INSULATE FLOATING SHIELD ENDS."),
        ("splice", f"INSTALL SPLICE ({items('splice')}) AT LOCATION SHOWN; SEE SPLICE TABLE."),
        ("heatshrink", f"RECOVER HEATSHRINK BOOT ({items('heatshrink')}) OVER BACKSHELL CABLE CLAMP."),
        ("label", f"INSTALL IDENTIFICATION LABEL ({items('label')}) ADJACENT TO CONNECTOR; MARK PER LABEL SCHEDULE."),
        ("wire_label", f"INSTALL WIRE MARKER ({items('wire_label')}) AT EACH END OF EACH WIRE; MARK WITH WIRE ID."),
        ("wire_heatshrink", f"INSTALL HEATSHRINK SLEEVE ({items('wire_heatshrink')}) AT EACH END OF EACH WIRE."),
    ]
    for cat, text in flagged:
        if items(cat):
            notes.append(Note(text, (cat,)))
    if any(gr.shielded for gr in active_groups) and not items("shield_term"):
        notes.append(Note("TERMINATE SHIELDS PER WIRE GROUPS TABLE. INSULATE FLOATING SHIELD ENDS."))
    return notes


def notes_block(notes: list[Note], width: float) -> Group:
    """Numbered notes; flag notes get their number in a triangle (Y14.100)."""
    g = Group(layer="NOTES")
    g.text(0, 9, "NOTES:", size=T + 1, bold=True)
    y = 24.0
    for i, note in enumerate(notes, start=1):
        if note.flagged:
            flag_symbol(g, 6, y - 2.5, i)
        else:
            g.text(0, y, f"{i}.", size=T)
        for line in wrap(note.text, T, width - 20):
            g.text(20, y, line, size=T)
            y += T + 3
        y += 3
    return g


# ---------------------------------------------------------------------------
# Table rows
# ---------------------------------------------------------------------------
def parts_list_rows(design: CableDesign, bom: list[BomItem], note_of: dict[str, int]) -> tuple[list[str], list[list[str]]]:
    headers = ["FIND NO", "QTY REQD", "CAGE CODE", "PART OR IDENTIFYING NO", "NOMENCLATURE OR DESCRIPTION", "NOTE"]
    rows = []
    for b in bom:
        part = design.library.get(b.pn)
        qty = b.qty_text() + (f" {b.unit}" if b.unit != "EA" and b.qty is not None else "")
        note = str(note_of[b.category]) if b.category in note_of else ""
        rows.append([str(b.item), qty, part.cage if part else "", b.pn, b.description, note])
    return headers, rows


def wire_list_rows(design: CableDesign) -> tuple[list[str], list[list[str]]]:
    headers = ["WIRE", "FROM", "PIN", "TO", "PIN", "SIGNAL", "AWG", "COLOR", "WIRE P/N", "GROUP",
               f"LENGTH ({design.units})", "NOTES"]
    rows = []
    for w in design.wires:
        length = design.wire_length(w)
        gr = design.group(w.group) if w.group else None
        wire_pn = w.wire_pn or (f"({gr.cable_pn})" if gr and gr.cable_pn else "")
        rows.append([w.wire_id, w.from_ref, w.from_pin, w.to_ref, w.to_pin, w.signal, w.gauge, w.color.upper(),
                     wire_pn, w.group, fmt_length(length) if length is not None else "AR", w.notes])
    return headers, rows


def _term_text(design: CableDesign, gr, ref: str) -> str:
    if not ref:
        return ""
    if design.is_splice(ref):
        return f"{ref}: (SPLICE)"
    kind, pin = parse_shield_term(design.shield_term_at(gr, ref), ref)
    if not gr.shielded:
        return ""
    if kind == "PIN":
        return f"{ref}: PIN {pin}"
    if kind == SHIELD_BACKSHELL:
        return f"{ref}: {design.shell_name(ref)}"
    return f"{ref}: {kind or 'TBD'}"


def group_rows(design: CableDesign, items: dict[str, int]) -> tuple[list[str], list[list[str]]]:
    headers = ["GROUP", "TYPE", "WITHIN", "WIRES", "CABLE P/N", "SHIELD P/N", "SHIELD TERM", "SHIELD (FROM END)",
               "SHIELD (TO END)", "NOTES"]
    rows = []
    for gr in design.groups:
        members = design.group_members(gr.group_id)
        if not members:
            continue
        refs = design.group_refs(gr.group_id)
        a = refs[0]
        term = gr.shield_term_pn + (f" (FIND NO. {items[gr.shield_term_pn]})" if gr.shield_term_pn in items else "")
        kids = [k.group_id for k in design.group_children(gr.group_id) if design.group_members(k.group_id)]
        wires = compress_refs([w.wire_id for w in design.direct_members(gr.group_id)], 40)
        contents = ", ".join(x for x in (", ".join(kids), wires) if x)
        far = "; ".join(t for t in (_term_text(design, gr, r) for r in refs[1:]) if t)
        rows.append([gr.group_id, gr.kind.upper(), gr.parent if design.group(gr.parent) else "", contents,
                     gr.cable_pn, gr.shield_pn, term, _term_text(design, gr, a), far, gr.notes])
    return headers, rows


def splice_rows(design: CableDesign, items: dict[str, int]) -> tuple[list[str], list[list[str]]]:
    headers = ["SPLICE", "FIND NO", "SPLICE P/N", "LOCATION", "WIRES", "NOTES"]
    rows = []
    for sp in design.splices:
        wires = [w.wire_id for w in design.wires if sp.ref in (w.from_ref, w.to_ref)]
        if not wires:
            continue
        value, ref = splice_location(design, sp)
        loc = f"{fmt_length(value)} {design.units} FROM {ref}" if value is not None else "AR"
        rows.append([sp.ref, str(items.get(sp.splice_pn, "")), sp.splice_pn, loc, ", ".join(wires), sp.notes])
    return headers, rows


def _end_text(ref: str, pin: str) -> str:
    return f"{ref}-{pin}" if pin else ref


def label_schedule_rows(design: CableDesign, items: dict[str, int]) -> tuple[list[str], list[list[str]]]:
    headers = ["FIND NO", "LABEL P/N", "LEGEND", "LOCATION", "QTY"]
    rows = []
    for c in design.connectors:
        if c.label_pn:
            rows.append([str(items.get(c.label_pn, "")), c.label_pn, c.legend, f"CABLE, ADJACENT TO {c.ref}", "1"])
    for w in design.wires:
        if w.label_pn:
            rows.append([str(items.get(w.label_pn, "")), w.label_pn, w.wire_id,
                         f"WIRE {w.wire_id}, AT {_end_text(w.from_ref, w.from_pin)} AND {_end_text(w.to_ref, w.to_pin)}", "2"])
    return headers, rows


# ---------------------------------------------------------------------------
# Sheet assembly
# ---------------------------------------------------------------------------
def _new_sheet(w: float, h: float, name: str, design: CableDesign) -> tuple[Sheet, Frame]:
    sheet = Sheet(w, h, name=name)
    border = Group(layer="BORDER")
    frame = draw_frame(border, w, h)
    draw_reverse_block(border, frame, design)
    sheet.root.add(border)
    return sheet, frame


def _heading(g: Group, x: float, y: float, text: str) -> float:
    g.text(x, y + BODY_FONT, text, size=BODY_FONT, bold=True)
    return y + BODY_FONT + 10


def _place(group: Group, box: tuple[float, float, float, float], max_scale: float, **kw) -> bool:
    """Fit ``group`` into ``box`` at no less than the minimum view scale. Returns False if it can't fit."""
    group.fit_into(*box, max_scale=max_scale, **kw)
    if group.scale + 1e-6 >= MIN_VIEW_SCALE:
        return True
    return False


def _build(design: CableDesign, sheet_size: str, force: bool) -> tuple[list[Sheet], list[str], bool]:
    """Lay out every sheet at ``sheet_size``. ``ok`` is False if anything needed text below the ASME minimum."""
    from .drc import run_drc

    letter, W, H = SHEET_SIZES[sheet_size]
    bom = build_bom(design)
    items = item_numbers(bom)
    warnings: list[str] = []
    ok = True
    S = MIN_VIEW_SCALE

    bundles = run_drc(design).bundles

    def make_notes(total_sheets: int) -> list[Note]:
        return [Note(t) for t in design.rendered_notes()] + auto_notes(design, bom, (FIRST_TABLE_SHEET, total_sheets), bundles)

    # Flag-note numbers don't depend on the sheet count, so they can be fixed now
    note_of: dict[str, int] = {}
    for i, n in enumerate(make_notes(FIRST_TABLE_SHEET), start=1):
        for cat in n.flag_categories:
            note_of[cat] = i

    # --- Sheets 4+: tables at exactly the minimum text scale --------------------------------------
    table_sheets: list[tuple[Sheet, Frame]] = []
    sheet, f = _new_sheet(W, H, "Wire list", design)
    y = _heading(sheet.root, f.x0 + PAD, f.y0 + DWG_BLOCK[1] + PAD, "WIRE LIST AND TABLES")
    table_sheets.append((sheet, f))
    region_w = f.x1 - f.x0 - 2 * PAD
    col_top, col_x, col_right = y, 0.0, 0.0
    table_specs = [
        ("WIRE LIST", wire_list_rows(design), [44, 34, 26, 34, 26, 110, 26, 40, 96, 34, 48, 110], frozenset({2, 4, 6, 10})),
        ("WIRE GROUPS AND SHIELDS", group_rows(design, items), [40, 110, 40, 96, 96, 80, 120, 96, 120, 120],
         frozenset({2})),
        ("SPLICES", splice_rows(design, items), [40, 36, 90, 130, 120, 120], frozenset({1})),
        ("LABEL SCHEDULE", label_schedule_rows(design, items), [36, 96, 60, 190, 26], frozenset({0, 4})),
    ]

    def flow_tables(specs, y, col_top, col_x, col_right, sheet, f):
        nonlocal ok
        for title, (headers, rows), caps, centered in specs:
            if not rows:
                continue
            widths = table_widths(headers, rows, caps=caps)
            s = S
            if sum(widths) * s > region_w:
                ok = False
                s = region_w / sum(widths)
            remaining, first = rows, True
            while remaining:
                bottom = f.y1 - CONT_TB_H - PAD
                capacity = int(((bottom - y) / s - TITLE_H - HEADER_H) // ROW_H)
                if capacity < 1:
                    if col_right and col_right + 24 + sum(widths) * s <= region_w:
                        col_x, y = col_right + 24, col_top
                    else:
                        sheet, f = _new_sheet(W, H, "Wire list (cont.)", design)
                        y = col_top = _heading(sheet.root, f.x0 + PAD, f.y0 + DWG_BLOCK[1] + PAD, "WIRE LIST AND TABLES (CONTINUED)")
                        col_x = col_right = 0.0
                        table_sheets.append((sheet, f))
                    continue
                chunk, remaining = remaining[:capacity], remaining[capacity:]
                col_right = max(col_right, col_x + sum(widths) * s)
                tg = Group(dx=f.x0 + PAD + col_x, dy=y, scale=s, layer="TABLES")
                used = draw_table(tg, 0, 0, headers, chunk, widths, title=title if first else f"{title} (CONTINUED)",
                                  center_cols=centered)
                sheet.root.add(tg)
                y += used * s + 20
                first = False
        return y, col_top, col_x, col_right, sheet, f

    # --- Sheet 1: notes and parts list -----------------------------------------------------------
    # Parts list above the title block, as tall as the space under the revision block allows; the rest continues
    # with the tables. Notes on the left.
    s1, f1 = _new_sheet(W, H, "Notes and parts list", design)
    rev_bottom = draw_revision_block(s1.root, f1, design)
    pl_headers, pl_rows = parts_list_rows(design, bom, note_of)
    pl_widths = table_widths(pl_headers, pl_rows or [[""] * 6], caps=[0, 0, 0, 150, 190, 0])
    pl_widths[-1] = max(pl_widths[-1], 34)
    strip_top = f1.y1 - TB_H
    pl_scale = S
    pl_w = sum(pl_widths) * pl_scale
    max_pl_h = (strip_top - PAD) - (rev_bottom + PAD)
    fit_rows = max(int((max_pl_h / pl_scale - TITLE_H - HEADER_H) // ROW_H), 0)
    sheet1_rows, overflow_parts = pl_rows[:fit_rows], pl_rows[fit_rows:]
    if overflow_parts:
        warnings.append(f"The parts list continues on the table sheets ({len(overflow_parts)} rows).")
        table_specs.insert(0, ("PARTS LIST (CONTINUED)", (pl_headers, overflow_parts), [0, 0, 0, 150, 190, 0],
                               frozenset({0, 1, 2})))
    flow_tables(table_specs, y, col_top, col_x, col_right, sheet, f)
    total = FIRST_TABLE_SHEET - 1 + len(table_sheets)
    notes = make_notes(total)
    marks = _Marks(flags={b.item: note_of[b.category] for b in bom if b.category in note_of})

    pl_g = Group(layer="TABLES", scale=pl_scale)
    pl_h = draw_table(pl_g, 0, 0, pl_headers, sheet1_rows, pl_widths, title="PARTS LIST", center_cols=frozenset({0, 1, 2}),
                      flag_cols=frozenset({5}), upward=True) * pl_scale
    pl_g.dx, pl_g.dy = f1.x1 - pl_w, strip_top - pl_h
    s1.root.add(pl_g)
    if pl_w > (f1.x1 - f1.x0) * 0.6:
        ok = False

    top = f1.y0 + DWG_BLOCK[1] + PAD
    notes_w_pt = f1.x1 - max(pl_w, REV_W) - f1.x0 - 3 * PAD
    ng = notes_block(notes, notes_w_pt / S)
    ng.scale = S
    nb = ng.bounds()
    ng.dx, ng.dy = f1.x0 + PAD - nb[0] * S, top - nb[1] * S
    if top + (nb[3] - nb[1]) * S > strip_top - PAD:
        ok = False
    s1.root.add(ng)

    # --- Sheet 2: assembly view with each connector's pinout under it -----------------------------
    s_av, f_av = _new_sheet(W, H, "Assembly", design)
    top = _heading(s_av.root, f_av.x0 + PAD, f_av.y0 + DWG_BLOCK[1] + PAD, "ASSEMBLY VIEW AND CONNECTOR PINOUTS (NOT TO SCALE)")
    av = assembly_view(design, items, marks)
    # Scaled down as far as the ASME minimum letter height allows; beyond that the sheet size goes up
    if not _place(av, (f_av.x0 + PAD, top + 6, f_av.x1 - f_av.x0 - 2 * PAD, f_av.y1 - CONT_TB_H - 2 * PAD - (top + 6)),
                  max_scale=S * 1.5):
        ok = False
    s_av.root.add(av)

    # --- Sheet 3: wiring diagram --------------------------------------------------------------------
    s2, f2 = _new_sheet(W, H, "Wiring diagram", design)
    top = _heading(s2.root, f2.x0 + PAD, f2.y0 + DWG_BLOCK[1] + PAD, "WIRING DIAGRAM")
    wd = wiring_diagram(design)
    if not _place(wd, (f2.x0 + PAD, top + 6, f2.x1 - f2.x0 - 2 * PAD, f2.y1 - CONT_TB_H - PAD - (top + 6)),
                  max_scale=S * 1.6, valign="top"):
        ok = False
    s2.root.add(wd)

    sheets = [(s1, f1), (s_av, f_av), (s2, f2), *table_sheets]
    for n, (sheet, frame) in enumerate(sheets, start=1):
        tbg = Group(layer="TITLE_BLOCK")
        if n == 1:
            draw_application_block(tbg, frame, design)
            draw_tolerance_block(tbg, frame, design)
            draw_title_block(tbg, frame, design, letter, n, total)
        else:
            draw_continuation_block(tbg, frame, design, letter, n, total)
        sheet.root.add(tbg)
    s1.meta = {"balloons": sorted(marks.ballooned), "find_numbers": [b.item for b in bom],
               "flag_notes": note_of, "sheet_size": sheet_size}
    if not ok and not force:
        warnings.append(f"Content doesn't fit {sheet_size} at the ASME minimum letter height.")
    return [s for s, _ in sheets], warnings, ok


def build_drawing(design: CableDesign, sheet_size: str = DEFAULT_SHEET, auto_size: bool = True) -> tuple[list[Sheet], list[str]]:
    """Return the drawing sheets and layout warnings.

    With ``auto_size`` the drawing moves to the next larger sheet of the same family (B → C → D → E, A3 → A2 → A1 → A0)
    until everything fits at the ASME minimum letter height. ``sheet_size`` is the smallest size allowed.
    """
    candidates = larger_sizes(sheet_size) if auto_size else [sheet_size]
    result = None
    for size in candidates:
        sheets, warnings, ok = _build(design, size, force=False)
        result = (sheets, [w for w in warnings if "doesn't fit" not in w])
        if ok:
            if size != sheet_size:
                result[1].insert(0, f"Sheet size increased from {sheet_size} to {size} so text meets the ASME "
                                    f"Y14.2 minimum letter height.")
            for s in sheets:
                s.meta["layout_warnings"] = list(result[1])
            return result
    sheets, warnings = result
    warnings.append(f"Even {candidates[-1]} is too small at the ASME minimum letter height; some views or tables "
                    f"were reduced below it. Split the drawing or simplify the views.")
    sheets[0].meta["layout_warnings"] = list(warnings)
    return sheets, warnings
