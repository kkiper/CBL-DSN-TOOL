# Cable Drawing Tool

Turns a wiring list plus your **connector, contact, backshell, heatshrink, label and wire part numbers** into a
cable assembly drawing package, with twisted pairs, shields, splices, a parts library, and a design rule check (DRC).
The drawing exports as PDF, SVG, or DXF.

| Sheet | Contents |
|---|---|
| 1 | Assembly view (connectors, backshells, heatshrink boots, ID labels, splices, lengths, item balloons), bill of materials, notes |
| 2 | Wiring diagram: a pin-out table per connector; wires drawn pin to pin or to splice nodes; twisted-pair marks, shield and cable-jacket outlines, and shield terminations (to backshell, drain to a pin, or floating) |
| 3+ | Wire list, wire groups and shields, splices, and label schedule (continued onto more sheets if needed) |

Every sheet has a zoned border and a title block. Sheet sizes: ANSI B, C and D, and ISO A3, A2 and A1.

```bash
streamlit run cable_app.py
```

1. Upload a wiring list (or load a sample) and, optionally, your **parts library**. Set the title block in the sidebar.
2. Fill in the tabs: **Connectors**, **Groups & shields**, **Splices**, **Parts library**, **Notes**. Connectors, groups,
   splices and part numbers named in the wire list get rows automatically.
3. Review the **design rule check**, preview the sheets, and download the PDF, DXF, SVG, BOM, DRC report, or
   **Save project (.xlsx)**. Upload the saved project later to continue where you left off.

Command line:

```bash
python -m cable_tool samples/cable_wirelist.csv -c samples/cable_connectors.csv -g samples/cable_groups.csv \
    -s samples/cable_splices.csv -l samples/parts_library.csv --length 48 --dwg-no W101-001 \
    -o W101-001.pdf --dxf dxf/ --svg svg/ --bom bom.csv --drc drc.csv --strict
python -m cable_tool samples/y_harness_wirelist.csv -c samples/y_harness_connectors.csv -l samples/parts_library.csv --sheet D
```

`--strict` exits with status 1 if the DRC finds errors (useful in a release check). `-l` can be repeated; later files win.

### Input tables

All tables can be CSV or Excel. Headers are matched loosely, and title rows above the header are skipped. A single
workbook can hold all of them on sheets named *Wire List*, *Connectors*, *Groups*, *Splices*, *Parts Library*,
*Title Block* and *Notes*. The project file the tool saves uses exactly that layout.

**Wiring list** (one row per wire):

| Column | Required | Also accepted as |
|---|---|---|
| From, To | yes | From Conn, Source / Destination. `P1-3`, `P1:3` or `P1.3` are split into connector and pin. `SP1`, `SP2`... are splices. |
| From Pin, To Pin | for connectors | Pin A / Pin B, From Contact |
| Wire ID | no (W1, W2... assigned) | Wire, Wire No, Circuit |
| Signal, Gauge, Color | no | Function / Net, AWG, Colour |
| Wire P/N | no | Wire Type, Part Number. Leave blank for conductors of a cable (Group with a Cable P/N). |
| Length | no | Cut Length. Overrides the length worked out from the cable lengths. |
| Wire Label P/N, Wire Heatshrink P/N | no | Marker P/N, Sleeve P/N. Installed at **both** ends of the wire (qty 2 per wire). |
| Group | no | Pair, Twisted Pair, Shield Group, Cable. Wires with the same group are twisted, shielded or in one cable. |
| Notes | no | Remarks |

**Connectors**: `Ref`, `Description`, `Connector P/N`, `Contact P/N` (overrides the library's default contact),
`Backshell P/N`, `Heatshrink P/N` (boot over the backshell), `Label P/N`, `Label Text`, and `Length` (connector face to breakout).

**Groups**: `Group`, `Type` (TWISTED PAIR, TWISTED TRIPLE, SHIELDED, SHIELDED TWISTED PAIR, JACKETED CABLE),
`Cable P/N` (a ready-made cable such as an M27500 shielded pair; its wires are the conductors and the BOM counts the
cable by length), `Shield P/N` (braid over a built-up group), `Shield Term P/N` (solder sleeve, band, etc., one per
terminated end), and `Shield Term From` / `Shield Term To`: `BACKSHELL`, `FLOAT`, or a pin (`11` or `P2-11`) at the
group's From / To connector. A shield drain to a pin with no wire adds that pin to the connector's pin-out.

**Splices**: `Splice`, `Splice P/N`, `Near` (the connector whose leg the splice is on) and `Distance` (from that
connector's face). The location sets the length of every wire to the splice and places the splice on the assembly view.

**Parts library** (one row per part number; only `P/N` is required). Dimensions are inches unless the header says mm,
for example `OD (mm)`.

| Type | Parameters used |
|---|---|
| wire | AWG, OD (insulation) |
| cable | OD (jacket), Conductors, AWG |
| connector | Contact P/N (default contact), Contacts (cavity count); AWG Min/Max and Dia Min/Max when contacts aren't separate parts |
| contact | AWG Min/Max (accepted wire), Dia Min/Max (insulation OD sealing range) |
| backshell | Dia Min/Max = cable clamp range |
| heatshrink, label, marker | Dia Min = fully recovered ID, Dia Max = expanded (as supplied) ID |
| splice | AWG Min/Max (each wire), CMA Min/Max (total circular-mil area of all wires in the splice) |
| shield_term | Dia Min/Max over the shielded cable or group |
| shield | Wall (added to a built-up group's diameter) |

Library descriptions are used in the bill of materials. `samples/parts_library.csv` shows the format. **Its values are
examples, not datasheet values.** Build your library from the manufacturers' datasheets.

### Design rule check

| Rule | Checks | Severity |
|---|---|---|
| Contact wire size | Each wire's gauge is within its contact's (or connector's) AWG range, at every pin | Error |
| Contact sealing range | Wire insulation OD is within the contact/grommet sealing range | Warning |
| Contact count | Pins used (wires plus shield drains) don't exceed the connector's contacts | Error |
| Splice wire size | Every wire in a splice is within its AWG range, and the total CMA is within its CMA range | Error |
| Backshell / Boot / Label fit | Bundle diameter at each connector vs. clamp range, boot and label sleeve recovered/expanded IDs | Error if too big; warning if too small to grip |
| Wire marker / sleeve fit | Wire OD vs. marker and sleeve recovered/expanded IDs | Error / warning |
| Shield termination | Shields terminated at each end; termination part fits the shielded group; drain pin not shared with another wire; shield not floating at both ends | Warning |
| Groups | Pair/triple has 2/3 wires; group wires share the same ends; cable conductor count and AWG match | Warning |
| Wire gauge | Wire list gauge matches the wire's library AWG | Warning |
| Part type | A part is used where its library type makes sense (for example, not a wire as a backshell) | Warning |
| Completeness | Missing part numbers, pins, duplicate IDs, unknown lengths, unused connectors/splices | Warning |
| Parts library | Parts that aren't in the library, or are missing the parameter a check needs (the check is skipped) | Info |

**Bundle diameter** at a connector counts every wire and cable that ends there (a cable or built-up shielded group
counts once, at its OD or at its members' bundle plus shield wall). It uses the common rule of thumb
*D ≈ 1.2 × √(Σ dᵢ²)*. Wire ODs come from the library, or are estimated from AWG for thin-wall wire, and the report says
when they were estimated. The calculated diameters are also added to the drawing notes.

### Lengths and quantities

- **Two-connector cable:** enter the overall length (sidebar or `--length`). **Harness with a breakout:** enter each
  connector's length to the breakout. **Splices** need *Near* and *Distance*. A per-wire **Length** overrides all of these.
  Lengths that can't be worked out show as **AR** (as required) in the BOM.
- Connectors, backshells, boots and labels are 1 per connector end. **Contacts** are 1 per pin used (wires plus shield
  drains). Wire markers and wire heatshrink are 2 per wire. Shield terminations are 1 per terminated shield end.
  Cables and braid are counted by length. Parts with the same P/N are combined into one BOM item.

### DXF output

One AutoCAD R12 ASCII DXF per sheet, at true size in inches, with layers BORDER, TITLE_BLOCK, ASSEMBLY, CABLE, WIRING,
SHIELDS, TABLES and NOTES. Dashed lines use the DASHED line type. R12 opens in AutoCAD, SolidWorks, Inventor, Creo,
DraftSight, LibreCAD, QCAD and most other CAD programs.

The part numbers and parameters in the samples are illustrative examples (D38999 / MS3126 connectors, M39029
contacts, M85049 backshells, M22759 wire, M27500 cable, M81824 splices). Check every part number and value against
your own design, datasheets, and approved parts list.

### Running it

```bash
pip install -r requirements.txt
streamlit run cable_app.py
```

Then open http://localhost:8501. `.streamlit/config.toml` makes the app listen only on `localhost` and turns off
Streamlit's usage statistics. Everything is processed on your computer.

### Example output

`examples/` holds the drawing package generated from the W101 sample (`samples/cable_*.csv` plus
`samples/parts_library.csv`): `W101-001.pdf`, one DXF per sheet in `examples/dxf/`, and the design rule check report
`W101-001_drc.csv`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
