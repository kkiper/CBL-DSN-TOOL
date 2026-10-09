"""Wire size and bundle diameter calculators (used by the desktop app's Calculators tab).

Conductor data follow the standard M22759 (SAE AS22759) stranding for tin- or silver-coated copper, ASTM B286
construction; ODs are approximate nominal finished diameters of M22759/16 and /32. **Check values against the
current slash sheets before relying on them.**
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .library import PACKING_FACTOR, circular_mils, parse_awg

MM2_PER_CMIL = 5.067075e-4          # 1 circular mil = pi/4 * (0.001 in)^2 = 5.067e-4 mm²
MM_PER_IN = 25.4

# AWG -> (strand count, strand AWG, nominal circular mils). 1/0 is AWG 0, 2/0 is -1, 3/0 is -2, 4/0 is -3.
M22759_CONDUCTORS: dict[int, tuple[int, int, int]] = {
    26: (19, 38, 304), 24: (19, 36, 475), 22: (19, 34, 754), 20: (19, 32, 1216), 18: (19, 30, 1900),
    16: (19, 29, 2426), 14: (19, 27, 3830), 12: (37, 28, 5874), 10: (37, 26, 9354), 8: (133, 29, 16983),
    6: (133, 27, 26813), 4: (133, 25, 42613), 2: (665, 30, 66500), 1: (817, 30, 81700), 0: (1045, 30, 104500),
    -1: (1330, 30, 133000), -2: (1665, 30, 166500), -3: (2109, 30, 210900),
}

# Approximate nominal finished OD (in) by AWG, per slash sheet (also used by tools/gen_libraries.py)
WIRE_SPECS = {
    "16": {
        "desc": "WIRE, ETFE, TIN-COATED COPPER, 600 V, 150 C",
        "od": {24: 0.046, 22: 0.052, 20: 0.062, 18: 0.071, 16: 0.081, 14: 0.099, 12: 0.120, 10: 0.153, 8: 0.215},
    },
    "32": {
        "desc": "WIRE, XL-ETFE, TIN-COATED HS COPPER ALLOY, LIGHT WEIGHT, 600 V, 150 C",
        "od": {26: 0.034, 24: 0.040, 22: 0.046, 20: 0.054, 18: 0.064, 16: 0.074, 14: 0.091, 12: 0.111},
    },
}


def awg_label(awg: float) -> str:
    """20 -> "20", 0 -> "1/0", -3 -> "4/0"."""
    if awg <= 0 and float(awg).is_integer():
        return f"{1 - int(awg)}/0"
    return f"{awg:g}"


def cma_to_mm2(cma: float) -> float:
    return cma * MM2_PER_CMIL


def mm2_to_cma(mm2: float) -> float:
    return mm2 / MM2_PER_CMIL


def cma_to_awg(cma: float) -> float:
    """Equivalent solid-conductor AWG of a cross-section (inverse of library.circular_mils)."""
    return 36 - 39 * math.log(math.sqrt(cma) / 5) / math.log(92)


def awg_to_cma(awg: float) -> float:
    """Nominal CMA of an M22759 conductor of that size, or the solid-conductor CMA for other sizes."""
    if float(awg).is_integer() and int(awg) in M22759_CONDUCTORS:
        return M22759_CONDUCTORS[int(awg)][2]
    return circular_mils(awg)


def strand_cma(size: float, unit: str = "AWG") -> float:
    """Circular mils of one strand given as an AWG, or a diameter in inches ("in") or millimetres ("mm")."""
    if unit == "AWG":
        return circular_mils(size)
    d_mils = size * 1000 if unit == "in" else size / MM_PER_IN * 1000
    return d_mils * d_mils


def strands_to_cma(size: float, count: int, unit: str = "AWG") -> float:
    return strand_cma(size, unit) * count


def nearest_m22759(cma: float) -> int:
    """M22759 size closest to ``cma`` (by ratio)."""
    return min(M22759_CONDUCTORS, key=lambda a: abs(math.log(M22759_CONDUCTORS[a][2] / cma)))


def smallest_m22759_at_least(cma: float) -> int | None:
    """Smallest M22759 size whose nominal CMA is at least ``cma`` (None if it's bigger than 4/0)."""
    bigger = [a for a, (_n, _s, c) in M22759_CONDUCTORS.items() if c >= cma * 0.999]
    return max(bigger) if bigger else None


def typical_wire_od(slash: str, awg: float) -> float | None:
    spec = WIRE_SPECS.get(slash)
    return spec["od"].get(int(awg)) if spec and float(awg).is_integer() else None


@dataclass
class SizeResult:
    cma: float
    mm2: float
    awg: float                  # equivalent solid AWG
    nearest: int                # nearest M22759 size
    at_least: int | None        # smallest M22759 size with at least this CMA

    @property
    def nearest_error(self) -> float:
        """How far the nearest M22759 size's CMA is from this one, in percent."""
        return (M22759_CONDUCTORS[self.nearest][2] / self.cma - 1) * 100


def size_from(mode: str, value: float | str, count: int = 1, unit: str = "AWG") -> SizeResult | None:
    """Convert from AWG ("1/0" accepted), CMA, mm², or strands (``value`` = strand size, ``count`` strands)."""
    try:
        if mode == "AWG":
            awg = parse_awg(value) if isinstance(value, str) else float(value)
            if awg is None:
                return None
            cma = awg_to_cma(awg)
        elif mode == "CMA":
            cma = float(value)
        elif mode == "mm2":
            cma = mm2_to_cma(float(value))
        elif mode == "Strands":
            cma = strands_to_cma(float(value), int(count), unit)
        else:
            raise ValueError(mode)
    except (TypeError, ValueError):
        return None
    if not cma or cma <= 0:
        return None
    return SizeResult(cma, cma_to_mm2(cma), cma_to_awg(cma), nearest_m22759(cma), smallest_m22759_at_least(cma))


# --- Bundle ------------------------------------------------------------------------------------------------
@dataclass
class BundleRow:
    kind: str                   # wire | cable
    pn: str
    od: float | None            # inches
    qty: int = 1
    awg: float | None = None


@dataclass
class BundleResult:
    diameter: float | None      # inches
    sum_d2: float
    items: int
    wires: int
    cables: int
    missing: int                # rows with a quantity but no OD (left out)


def bundle(rows: list[BundleRow], packing: float = PACKING_FACTOR) -> BundleResult:
    """D = packing x sqrt(sum of d²) over every wire and cable; a single item is its own OD."""
    counted = [r for r in rows if r.qty > 0 and r.od]
    sum_d2 = sum(r.od * r.od * r.qty for r in counted)
    n = sum(r.qty for r in counted)
    if n == 0:
        dia = None
    elif n == 1:
        dia = counted[0].od
    else:
        dia = packing * math.sqrt(sum_d2)
    return BundleResult(dia, sum_d2, n, sum(r.qty for r in counted if r.kind == "wire"),
                        sum(r.qty for r in counted if r.kind == "cable"),
                        sum(1 for r in rows if r.qty > 0 and not r.od))


def rows_from_connector(design, ref: str) -> list[BundleRow]:
    """Bundle rows for what lands on connector ``ref`` in ``design``, combined by P/N and OD."""
    from .drc import bundle_items

    out: dict[tuple, BundleRow] = {}
    for it in bundle_items(design, ref):
        key = (it.kind, it.pn, it.od)
        if key in out:
            out[key].qty += 1
        else:
            out[key] = BundleRow(it.kind, it.pn, it.od, 1, it.awg)
    return list(out.values())
