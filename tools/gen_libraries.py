"""Generate the sample parts libraries in libraries/: D38999 Series III connectors and contacts, M22759 wire.

Run from the repository root:  python tools/gen_libraries.py

The part-number structure, contact assignments and accepted wire sizes follow MIL-DTL-38999, MIL-STD-1560
(insert arrangements), M39029 and M22759. Wire ODs and grommet sealing ranges are approximate nominal values for
illustration. Check every value against the current slash sheets / manufacturer data before relying on the DRC.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cable_tool import calc  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "libraries"
HEADERS = ["P/N", "Type", "Description", "CAGE", "AWG", "OD", "AWG Min", "AWG Max", "Dia Min", "Dia Max",
           "Contact P/N", "Contacts", "Contacts Included", "Color", "Notes"]
VERIFY = "SAMPLE DATA - VERIFY AGAINST CURRENT SPEC SHEET"

# --- D38999 Series III -------------------------------------------------------------------------------
# Crimp contacts (M39029/56 socket, M39029/58 pin): accepted AWG and approximate wire sealing range (in)
CONTACTS = {
    "22D": {"socket": "M39029/56-348", "pin": "M39029/58-360", "awg": (22, 28), "seal": (0.030, 0.054)},
    "20": {"socket": "M39029/56-351", "pin": "M39029/58-363", "awg": (20, 24), "seal": (0.040, 0.083)},
    "16": {"socket": "M39029/56-352", "pin": "M39029/58-364", "awg": (16, 20), "seal": (0.065, 0.109)},
    "12": {"socket": "M39029/56-353", "pin": "M39029/58-365", "awg": (12, 14), "seal": (0.097, 0.142)},
}

SHELLS = {"A": 9, "B": 11, "C": 13, "D": 15, "E": 17, "F": 19, "G": 21, "H": 23, "J": 25}

# Single-contact-size insert arrangements (MIL-STD-1560): (shell letter, arrangement) -> (contacts, size)
INSERTS = {
    ("A", "35"): (6, "22D"), ("B", "35"): (13, "22D"), ("C", "35"): (22, "22D"), ("D", "35"): (37, "22D"),
    ("E", "35"): (55, "22D"), ("F", "35"): (66, "22D"), ("G", "35"): (79, "22D"), ("H", "35"): (100, "22D"),
    ("J", "35"): (128, "22D"),
    ("A", "98"): (3, "20"), ("B", "98"): (6, "20"), ("C", "98"): (10, "20"), ("D", "18"): (18, "20"),
    ("D", "19"): (19, "20"), ("E", "26"): (26, "20"), ("F", "32"): (32, "20"), ("G", "41"): (41, "20"),
    ("H", "53"): (53, "20"), ("J", "61"): (61, "20"),
    ("C", "04"): (4, "16"), ("D", "05"): (5, "16"), ("E", "08"): (8, "16"), ("F", "11"): (11, "16"),
    ("G", "16"): (16, "16"), ("H", "21"): (21, "16"), ("J", "29"): (29, "16"),
}

CLASSES = {"26": "PLUG", "20": "RECEPTACLE, WALL MOUNT", "24": "RECEPTACLE, JAM NUT"}
FINISHES = {"F": "ELECTROLESS NICKEL", "W": "OLIVE DRAB CADMIUM", "Z": "BLACK ZINC NICKEL"}
GENDERS = {"S": ("socket", "SKT"), "P": ("pin", "PIN")}


def d38999_rows() -> list[list]:
    rows = []
    for size, c in CONTACTS.items():
        for gender, pn in (("SOCKET", c["socket"]), ("PIN", c["pin"])):
            rows.append([pn, "contact", f"CONTACT, {gender}, CRIMP, SIZE {size}", "", "", "", c["awg"][0], c["awg"][1],
                         c["seal"][0], c["seal"][1], "", "", "", "", f"D38999 SERIES III. AWG {c['awg'][0]}-{c['awg'][1]}. "
                         f"Dia = approx. wire sealing range. {VERIFY}"])
    for cls, kind in CLASSES.items():
        for finish, fin_desc in FINISHES.items():
            for (shell, arr), (count, size) in sorted(INSERTS.items(), key=lambda kv: (SHELLS[kv[0][0]], kv[0][1])):
                for g, (contact_kind, short) in GENDERS.items():
                    contact = CONTACTS[size][contact_kind]
                    base = f"D38999/{cls}{finish}{shell}{arr}{g}N"
                    # D38999 part numbers include their contacts; the -LC ("less contacts") version doesn't
                    for pn, included in ((base, True), (base + "-LC", False)):
                        desc = (f"CONNECTOR, {kind}, D38999 SERIES III, SHELL {SHELLS[shell]}, {count} {short} SIZE {size}, "
                                f"{fin_desc}" + ("" if included else ", LESS CONTACTS"))
                        supply = f"Supplied with {contact} contacts." if included else f"Less contacts: order {contact} separately."
                        notes = f"INSERT {SHELLS[shell]}-{arr}, N KEY. {supply} {VERIFY}"
                        if finish == "W":
                            notes = "CADMIUM FINISH: CHECK HAZARDOUS-MATERIAL RESTRICTIONS. " + notes
                        rows.append([pn, "connector", desc, "", "", "", "", "", "", "", contact, count,
                                     "YES" if included else "NO", "", notes])
    return rows


# --- M22759 wire ---------------------------------------------------------------------------------------
COLORS = {0: "BLK", 1: "BRN", 2: "RED", 3: "ORN", 4: "YEL", 5: "GRN", 6: "BLU", 7: "VIO", 8: "GRY", 9: "WHT"}

# Approximate nominal finished OD (in) by gauge: shared with the desktop app's calculators
WIRE_SPECS = calc.WIRE_SPECS


def m22759_rows() -> list[list]:
    rows = []
    for slash, spec in WIRE_SPECS.items():
        for awg, od in spec["od"].items():
            for code, color in COLORS.items():
                rows.append([f"M22759/{slash}-{awg}-{code}", "wire", f"{spec['desc']}, {awg} AWG, {color}", "", awg, od,
                             "", "", "", "", "", "", "", color, f"M22759/{slash}. OD approx. nominal. {VERIFY}"])
    return rows


def write(name: str, rows: list[list]) -> Path:
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        w.writerows(rows)
    return path


if __name__ == "__main__":
    for name, rows in (("d38999_series_iii.csv", d38999_rows()), ("m22759_wire.csv", m22759_rows())):
        print(f"{write(name, rows)}: {len(rows)} parts")
