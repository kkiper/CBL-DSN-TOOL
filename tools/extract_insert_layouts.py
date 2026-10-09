"""Extract MIL-DTL-38999 Series III insert layouts from a vector PDF of the MIL-STD-1560 arrangement drawings.

Usage:  python tools/extract_insert_layouts.py insert-arrangements.pdf [-o cable_tool/data/d38999_insert_layouts.csv]

Made for the Glenair catalogue pages "MIL-DTL-38999 Series I, II and III Type Environmental Class Connectors,
Insert Arrangements (IAW MIL-STD-1560)". It reads the drawings as vectors, not pixels:

* insert outline  = circle assembled from arcs, Beziers or polyline segments,
* cavity          = small closed symbol inside it; its size separates the contact sizes of mixed arrangements,
* contact label   = the text next to the cavity (number or letter),
* arrangement     = the Series III code printed under the drawing (e.g. D35).

Positions are written relative to the insert centre and normalised to the insert radius (+x right, +y up), as
drawn, with each label's position and size so face views can reproduce the catalogue's label placement. Every
arrangement is checked against the contact table on the last page (count per contact size); any arrangement that
doesn't match is reported and left out. The PDF itself is not needed at run time.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber

SIZES = ["10", "12", "16", "20", "22D"]
# Per contact: label, cavity centre, contact size, cavity symbol diameter, label centre, label font size.
# Lengths are relative to the insert radius, +x right, +y up.
COLUMNS = ["Contact", "X", "Y", "Size", "D", "LX", "LY", "H"]


def _visible(obj, page) -> bool:
    return 0 <= obj["x0"] and obj["x1"] <= page.width and 0 <= obj["top"] and obj["bottom"] <= page.height


def _clusters(items, near):
    """Union-find clustering of items where near(a, b) is True."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if near(items[i], items[j]):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, it in enumerate(items):
        groups[find(i)].append(it)
    return list(groups.values())


def _bbox(group):
    return (min(c["x0"] for c in group), min(c["top"] for c in group),
            max(c["x1"] for c in group), max(c["bottom"] for c in group))


def _touch(a, b, tol=1.0):
    return not (a["x1"] + tol < b["x0"] or b["x1"] + tol < a["x0"] or a["bottom"] + tol < b["top"] or b["bottom"] + tol < a["top"])


def _bezier_bbox(obj):
    """True bounding box of a curve. pdfplumber's bbox only covers the path's on-curve points, so a circle drawn as
    two Bezier halves comes out flat; sample the Beziers instead."""
    pts, cur = [], None
    for seg in obj.get("path") or []:
        op, *ps = seg
        if op in ("m", "l"):
            cur = ps[-1]
            pts.append(cur)
        elif op == "c" and cur is not None:
            (x1, y1), (x2, y2), (x3, y3) = ps
            x0, y0 = cur
            for k in range(1, 9):
                t = k / 8
                a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
                pts.append((a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3))
            cur = (x3, y3)
    if not pts:
        return obj["x0"], obj["top"], obj["x1"], obj["bottom"]
    # path y is already in top-down page coordinates
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def segments(page):
    """Visible curves and lines as plain boxes {x0, top, x1, bottom} (cached per page)."""
    cache = getattr(page, "_segments", None)
    if cache is None:
        cache = []
        for obj in page.curves + page.lines:
            if not _visible(obj, page):
                continue
            x0, y0, x1, y1 = _bezier_bbox(obj) if obj["object_type"] == "curve" else (
                obj["x0"], obj["top"], obj["x1"], obj["bottom"])
            cache.append({"x0": x0, "top": y0, "x1": x1, "bottom": y1})
        page._segments = cache
    return cache


def outlines(page):
    """Insert outline circles: (cx, cy, r) in page coordinates (y down). Outlines are drawn as arcs, Beziers or
    polylines; a connected group of strokes with a square bounding box is taken as the outline."""
    strokes = [s for s in segments(page) if 2.5 < max(s["x1"] - s["x0"], s["bottom"] - s["top"]) < 90]
    out = []
    for g in _clusters(strokes, lambda a, b: _touch(a, b, 0.5)):
        x0, y0, x1, y1 = _bbox(g)
        w, h = x1 - x0, y1 - y0
        if 15 < w < 100 and abs(w - h) < max(1.5, 0.03 * w):
            out.append(((x0 + x1) / 2, (y0 + y1) / 2, (w + h) / 4))
    return out


def cavities(page, circle):
    """Cavity symbols inside an outline: (x, y, symbol diameter)."""
    cx, cy, r = circle
    small = [s for s in segments(page) if max(s["x1"] - s["x0"], s["bottom"] - s["top"]) < 8
             and math.hypot((s["x0"] + s["x1"]) / 2 - cx, (s["top"] + s["bottom"]) / 2 - cy) < r * 0.93]
    found = []
    for g in _clusters(small, lambda a, b: _touch(a, b, 0.2)):
        x0, y0, x1, y1 = _bbox(g)
        w, h = x1 - x0, y1 - y0
        if 1.2 < max(w, h) < 8 and abs(w - h) < 0.25 * max(w, h):
            found.append(((x0 + x1) / 2, (y0 + y1) / 2, max(w, h)))
    return found


def labels(page, circle, max_size=5.0):
    cx, cy, r = circle
    chars = sorted((c for c in page.chars if _visible(c, page) and c["size"] < max_size and c["text"].strip(" _")
                    and math.hypot((c["x0"] + c["x1"]) / 2 - cx, (c["top"] + c["bottom"]) / 2 - cy) < r * 1.02),
                   key=lambda c: (round(c["top"]), c["x0"]))
    tokens: list[dict] = []
    for c in chars:
        last = tokens[-1] if tokens else None
        if last and abs(c["top"] - last["top"]) < 1 and 0 <= c["x0"] - last["x1"] < c["size"] * 0.35:
            last["text"] += c["text"]
            last["x1"] = c["x1"]
        else:
            tokens.append({"text": c["text"], "x0": c["x0"], "x1": c["x1"], "top": c["top"], "bottom": c["bottom"],
                           "size": c["size"]})
    return [(t["text"], (t["x0"] + t["x1"]) / 2, (t["top"] + t["bottom"]) / 2, t["size"]) for t in tokens]


def drawings(page):
    """(Series III code, outline circle) pairs: each code in a "Series III" row, matched to the drawing above it."""
    circles = outlines(page)
    words = [w for w in page.extract_words() if _visible(w, page)]
    rows = sorted({round(w["top"]) for w in words if w["text"].startswith("III")})
    found = []
    for k, row in enumerate(rows):
        prev = rows[k - 1] if k else 0           # drawings for this block sit between the previous block's labels and these
        for w in words:
            if abs(w["top"] - row) >= 2 or not re.fullmatch(r"[A-J]\d{1,2},?", w["text"]):
                continue
            # The Series III code is the first code in its column of the "Series III, IV" row
            xc = (w["x0"] + w["x1"]) / 2
            above = [c for c in circles if abs(c[0] - xc) < max(c[2], 12) and prev < c[1] < row]
            if not above:
                continue
            circle = max(above, key=lambda c: c[1])          # nearest drawing above the label row
            if any(circle is f[1] for f in found):
                continue                                     # "G11, G11": second code is Series IV
            found.append((w["text"].rstrip(","), circle))
    return found


def contact_table(pdf) -> dict[str, Counter]:
    """Series III code -> Counter(size -> count), from the table page."""
    table: dict[str, Counter] = {}
    for page in pdf.pages:
        words = page.extract_words()
        head_rows = [w["top"] for w in words if w["text"] == "22D" and (w["x0"] + w["x1"]) / 2 < page.width * 0.55]
        if not head_rows:
            continue
        head_y = head_rows[0]
        heads = {w["text"]: (w["x0"] + w["x1"]) / 2 for w in words      # header line of the Series III table only
                 if w["text"] in SIZES and abs(w["top"] - head_y) < 2 and (w["x0"] + w["x1"]) / 2 < page.width * 0.55}
        if "22D" not in heads or "Series" not in {w["text"] for w in words}:
            continue
        cols = sorted(((x, s) for s, x in heads.items()), key=lambda t: t[0])
        lines = defaultdict(list)
        for w in words:
            lines[round(w["top"])].append(w)
        for _, ws in sorted(lines.items()):
            ws.sort(key=lambda w: w["x0"])
            codes = [w for w in ws if re.fullmatch(r"[A-J]\d{1,2}", w["text"])]
            if not codes:
                continue
            code = codes[0]
            nums = [w for w in ws if w["x0"] > code["x1"] and re.fullmatch(r"\d{1,3}", w["text"])]
            counts = Counter()
            # only columns of the MIL-DTL-38999 Series III table (left half of the page)
            for n in nums:
                xc = (n["x0"] + n["x1"]) / 2
                if xc > page.width * 0.55:
                    break
                size = min(cols, key=lambda t: abs(t[0] - xc))[1]
                counts[size] += int(n["text"])
            if counts and code["text"] not in table and code["x0"] < page.width * 0.55:
                table[code["text"]] = counts
    return table


def assign_sizes(diameters: list[float], expected: Counter) -> list[str] | None:
    """Contact size per cavity. Single-size: from the table. Mixed: split by symbol diameter in the table's
    proportions (bigger symbol = bigger contact), accepted only if there's a clear gap between the groups."""
    if len(expected) == 1:
        return [next(iter(expected))] * len(diameters)
    order = sorted(range(len(diameters)), key=lambda i: diameters[i])
    sizes_small_to_big = sorted(expected, key=lambda s: SIZES.index(s), reverse=True)   # 22D, 20, 16, 12, 10
    out = [""] * len(diameters)
    pos = 0
    groups = []
    for size in sizes_small_to_big:
        idx = order[pos:pos + expected[size]]
        pos += expected[size]
        groups.append([diameters[i] for i in idx])
        for i in idx:
            out[i] = size
    for a, b in zip(groups, groups[1:]):
        if not a or not b or max(a) >= min(b) - 0.15:
            return None
    return out


def extract(pdf_path: str):
    layouts: dict[str, list[dict]] = {}
    problems: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        table = contact_table(pdf)
        raw = []
        for page in pdf.pages:
            for code, circle in drawings(page):
                if code in {c for c, *_ in raw}:
                    continue
                raw.append((code, page, circle, cavities(page, circle), labels(page, circle)))
        for code, page, (cx, cy, r), cavs, labs in raw:
            expected = table.get(code)
            if expected is None:
                problems.append(f"{code}: not in the contact table")
                continue
            if len(cavs) != sum(expected.values()):
                problems.append(f"{code}: {len(cavs)} cavities drawn, table says {sum(expected.values())}")
                continue
            if len(labs) != len(cavs):
                problems.append(f"{code}: only {len(labs)} of {len(cavs)} contacts are labelled in the drawing "
                                "(numbering not fully documented here)")
                continue
            # assign each label to its nearest cavity, one-to-one
            pairs = sorted(((math.hypot(lx - x, ly - y), i, j) for i, (_t, lx, ly, _s) in enumerate(labs)
                            for j, (x, y, _d) in enumerate(cavs)))
            used_l, used_c, assign = set(), set(), {}
            for _dist, i, j in pairs:
                if i not in used_l and j not in used_c:
                    used_l.add(i)
                    used_c.add(j)
                    assign[j] = labs[i]
            sizes = assign_sizes([d for *_xy, d in cavs], expected)
            if sizes is None:
                problems.append(f"{code}: cavity symbols don't separate cleanly into the table's sizes {dict(expected)}")
                continue
            rows = []
            for j, (x, y, d) in enumerate(cavs):
                lab, lx, ly, ls = assign[j]
                rows.append({"Contact": lab, "X": (x - cx) / r, "Y": (cy - y) / r, "Size": sizes[j], "D": d / r,
                             "LX": (lx - cx) / r, "LY": (cy - ly) / r, "H": ls / r})
            if len({row["Contact"] for row in rows}) != len(rows):
                problems.append(f"{code}: duplicate contact labels")
                continue
            layouts[code] = rows
    return layouts, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default=str(Path(__file__).resolve().parents[1] / "cable_tool" / "data" / "d38999_insert_layouts.csv"))
    args = ap.parse_args(argv)
    layouts, problems = extract(args.pdf)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Arrangement"] + COLUMNS)
        for code in sorted(layouts, key=lambda c: (c[0], int(c[1:]))):
            for row in sorted(layouts[code], key=lambda t: (len(t["Contact"]), t["Contact"])):
                w.writerow([code] + [row[k] if isinstance(row[k], str) else f"{row[k]:.4f}" for k in COLUMNS])
    print(f"{len(layouts)} Series III arrangements written to {args.out}")
    for p in problems:
        print("skipped:", p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
