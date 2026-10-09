# Cable Designer

Design cable assemblies and harnesses on a canvas, and get an **ASME Y14-format drawing package** (PDF, DXF, SVG)
with a parts list, wiring diagram, wire list, and a design rule check (DRC) driven by your parts library.

- **Desktop app** (Windows / macOS / Linux): a Splice CAD–style harness editor. Drag connectors and parts from the
  library, wire pin to pin, group wires into twisted pairs and shields, add splices. The DRC and the drawing update
  as you work.
- **Command line** and a **web app** (Streamlit) using the same engine, for batch runs and quick browser use.

| Sheet | Contents |
|---|---|
| 1 | General and flag notes, parts list, revision block, application block, tolerance block, title block |
| 2 | Assembly view (connectors, backshells, boots, ID labels, splices, dimensions, find-number balloons, flag notes) with each connector's pinout drawn under it |
| 3 | Wiring diagram: a pin-out table per connector, including NC positions; wires pin to pin or to splice nodes; twisted-pair marks, shield and cable-jacket outlines, and shield terminations (to backshell, drain to a pin, or floating) |
| 4+ | Wire list, wire groups and shields, splices, label schedule, and any parts-list continuation |

## Desktop app

**Install:** download `CableDesigner-x.y.z-setup.exe` (Windows installer, which also associates `.cbl` files) or
`CableDesigner-macos.zip` from the repository's GitHub Releases. Neither needs Python. To run from source instead:

```bash
pip install -r requirements-desktop.txt
python -m cable_desktop                # or: python -m cable_desktop project.cbl
```

**Working on the canvas** (centre, *Harness* tab):

- **Add connectors** by dragging a connector part from the **Library** panel onto the canvas, or with *+ Connector*.
  The pin count comes from the part's *Contacts* in the library.
- **Wire** by dragging from one pin's port to another pin (or a splice). New wires use the *New wire* P/N in the
  toolbar, and gauge and colour come from the library.
- **Assign parts** by dropping a backshell, boot, label or contact onto a connector, or a wire, marker, sleeve or
  cable part onto a wire.
- **Group wires:** select wires, right-click, *Group as* twisted pair, shielded twisted pair, shielded, or jacketed
  cable. Set the shield terminations in the *Groups and shields* table.
- **Splices:** *+ Splice* or drop a splice part, then wire to it. Set *Near* / *Distance* in the *Splices* table to
  locate it.
- **Tables** at the bottom show the same data as a spreadsheet. **Properties** (right) edits the selected item.
  Renaming a connector, splice, group or part updates every reference to it.
- **Design rule check** runs as you edit. Items with errors are outlined red on the canvas, warnings amber.
  Double-click a finding to jump to the item.
- The **Drawing** tab previews every sheet. *Smallest sheet* sets the starting size (see below).
- *Design → Title block, revisions and notes* (Ctrl+T) fills the title block, application block, revision
  history and general notes. *File → Export drawing package* (Ctrl+E) writes PDF, DXF, SVG, BOM, DRC report and the
  project workbook.
- Every edit can be undone. Projects save as `.cbl` (JSON, including canvas positions). *File → Open* also reads
  wiring lists and project workbooks (`.xlsx`, `.csv`), and *File → Import* merges connector, group, splice and
  library tables into the open project. *File → Open sample* has two worked examples.

## Drawing format (ASME)

The drawings follow the ASME Y14 series as commonly applied. `cable_tool/asme.py` holds every value used, so you
can match your organization's edition and drafting manual.

| Standard | What the drawing does |
|---|---|
| Y14.1 | Sheet sizes ANSI B–E (ISO A3–A0), zoned border, full title block on sheet 1, continuation title block on later sheets, reverse-oriented drawing-number block |
| Y14.1 / Y14.100 | Title block with design activity, CAGE code, drawing number, size, revision, scale, weight, sheet n of m, contract number, and DRAWN / CHECKED / ENGR / APPROVED names and dates. Application block (NEXT ASSY / USED ON) and proprietary/distribution statement |
| Y14.2 | Minimum letter heights: 0.24 in title, drawing number and zone letters; 0.12 in all other text; 0.10 in block headings. Line weights: thick 0.6 mm (outlines, borders), thin 0.3 mm (dimensions, leaders, tables) |
| Y14.5 | "UNLESS OTHERWISE SPECIFIED" block (units, tolerance, interpret per Y14.5, do not scale) with the third-angle projection symbol. 3:1 arrowheads; lengths and splice locations dimensioned from the connector face; units not repeated on dimensions |
| Y14.34 | Parts list above the title block, reading upward: FIND NO, QTY REQD, CAGE CODE, PART OR IDENTIFYING NO, NOMENCLATURE OR DESCRIPTION, NOTE. Find-number balloons on the assembly view |
| Y14.35 | Revision block (ZONE, REV, DESCRIPTION, DATE, APPROVED) from the project's revision history |
| Y14.100 | Numbered general notes, plus flag notes (number in a triangle) at the feature, in the notes, and in the parts-list NOTE column |
| Y14.15 | Wiring-diagram conventions: connector pin-out tables, splice nodes, twisted pairs, shields with their terminations and the chassis-ground symbol |

**Text is never shrunk below the minimum letter height.** When the views or tables don't fit the chosen sheet at
that height, the drawing moves to the next size (B → C → D → E, or A3 → A2 → A1 → A0) and says so. `--fixed-size`
(CLI) keeps the requested size instead and reports the undersized text.

**Drawing format check:** the DRC also checks the generated sheets: letter heights, required title-block fields,
revision block vs. title block, and parts-list find numbers vs. balloons. These findings are reported under the rule
*Drawing format*.

## Web app and command line

```bash
pip install -r requirements.txt
streamlit run cable_app.py
```

```bash
python -m cable_tool samples/cable_wirelist.csv -c samples/cable_connectors.csv -g samples/cable_groups.csv \
    -s samples/cable_splices.csv -l samples/parts_library.csv --length 48 --dwg-no W101-001 \
    -o W101-001.pdf --dxf dxf/ --svg svg/ --bom bom.csv --drc drc.csv --strict
python -m cable_tool project.xlsx --sheet D -o drawing.pdf
```

- `--strict` exits with status 1 if the DRC finds errors (useful in a release check).
- `-l` can be repeated; later files win.
- `--sheet` is the smallest sheet size to use; `--fixed-size` stops the automatic sizing.

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
| connector | Contact P/N (default contact), Contacts (cavity count), Contacts Included (YES/NO; blank = D38999 P/Ns include them unless they end in `-LC`); AWG Min/Max and Dia Min/Max when contacts aren't separate parts |
| contact | AWG Min/Max (accepted wire), Dia Min/Max (insulation OD sealing range) |
| backshell | Dia Min/Max = cable clamp range |
| heatshrink, label, marker | Dia Min = fully recovered ID, Dia Max = expanded (as supplied) ID |
| splice | AWG Min/Max (each wire), CMA Min/Max (total circular-mil area of all wires in the splice) |
| shield_term | Dia Min/Max over the shielded cable or group |
| shield | Wall (added to a built-up group's diameter) |

Every type can also have `Description` (used in the parts list) and `CAGE` (the parts-list CAGE CODE column). `samples/parts_library.csv` shows the format. **Its values are
examples, not datasheet values.** Build your library from the manufacturers' datasheets.

### Sample libraries

`libraries/` has two ready-made parts libraries. In the desktop app, use *File → Import → Sample library*; on the
command line, pass them with `-l`.

| File | Contents |
|---|---|
| `d38999_series_iii.csv` | 944 parts. D38999 Series III plugs (`/26`), wall-mount (`/20`) and jam-nut (`/24`) receptacles in F, W and Z finishes, pin and socket, N key, for 26 single-contact-size insert arrangements (size 22D, 20 and 16), each as the standard P/N (supplied with contacts) and the `-LC` (less contacts) P/N. Each has its contact count and linked M39029 contact. Also the M39029/56 and /58 crimp contacts (sizes 22D, 20, 16, 12) with their AWG ranges and approximate wire sealing ranges. |
| `m22759_wire.csv` | 170 wires. M22759/16 (24–8 AWG) and /32 (26–12 AWG), colour codes −0 to −9, with AWG and approximate nominal OD. |

They're generated by `tools/gen_libraries.py`; edit the tables there and rerun it to add arrangements, finishes or
wire specs. Part numbers, contact assignments and AWG ranges follow the specs. **ODs and sealing ranges are
approximate sample values: check them against the current slash sheets before relying on the DRC.** Mixed-size
insert arrangements aren't included, because a connector has one default contact P/N.

### Contacts supplied with connectors

D38999 part numbers come with their contacts unless they end in `-LC` (less contacts). For those connectors the parts
list doesn't add a contact line, the notes say which contacts are supplied with which find numbers, and the DRC still
checks every wire against the linked contact's AWG and sealing range. Set *Contacts Included* in the library to
override the rule for any part. A connector-table *Contact P/N* that differs from the supplied contact is a warning.

### Connector pinouts and NC positions

Sheet 2 draws a pinout under each connector whose insert arrangement is known. It is the front (engaging) face of
the connector called out in the parts list: every cavity with its contact letter or number, wired contacts filled,
unused (NC) contacts open, plus the P/N, insert arrangement, key position and contact type. The assembly view and its
pinouts are scaled together to fit the sheet, down to the ASME minimum letter height; past that the drawing moves to
the next sheet size (or, with a fixed sheet size, is drawn smaller with a format warning). Layouts are in
`cable_tool/data/d38999_insert_layouts.csv`: 33 MIL-DTL-38999 Series III arrangements (MIL-STD-1560), extracted from
the vector insert-arrangement drawings by `tools/extract_insert_layouts.py` and checked against the catalogue's
contact table. The arrangement comes from the D38999 P/N (shell letter plus arrangement number, e.g. `D38999/26WD19SN`
is insert 15-19).

- MIL-STD-1560 draws the front face of the pin insert; a socket connector's front face is its mirror image, so socket
  pinouts are mirrored to show the actual part. Verify this against MIL-STD-1560 for your application.
- **NC (no connection):** every contact position with no wire or shield drain is NC. Positions come from the insert
  layout, or 1 to *Contacts* from the library when the pins are numbered. NC positions are listed in the wiring
  diagram's pin tables (one row each, or a summary row when there are more than 24) and in a general note.
- The master keyway isn't shown, because the source drawings don't show it.
- Dense size-22D arrangements (D35, E35, F35, H35, J35 and others) aren't included: the source only labels the first
  contact of each ring, so their numbering isn't documented per cavity.

### Design rule check

| Rule | Checks | Severity |
|---|---|---|
| Contact wire size | Each wire's gauge is within its contact's (or connector's) AWG range, at every pin | Error |
| Contact sealing range | Wire insulation OD is within the contact/grommet sealing range | Warning |
| Contact count | Pins used (wires plus shield drains) don't exceed the connector's contacts | Error |
| Contact position | Every pin used exists in the connector's insert arrangement (when the layout is known; labels are case-sensitive) | Error |
| Contacts | A connector-table contact P/N differs from the contacts supplied with the connector | Warning |
| Splice wire size | Every wire in a splice is within its AWG range, and the total CMA is within its CMA range | Error |
| Backshell / Boot / Label fit | Bundle diameter at each connector vs. clamp range, boot and label sleeve recovered/expanded IDs | Error if too big; warning if too small to grip |
| Wire marker / sleeve fit | Wire OD vs. marker and sleeve recovered/expanded IDs | Error / warning |
| Shield termination | Shields terminated at each end; termination part fits the shielded group; drain pin not shared with another wire; shield not floating at both ends | Warning |
| Groups | Pair/triple has 2/3 wires; group wires share the same ends; cable conductor count and AWG match | Warning |
| Wire gauge | Wire list gauge matches the wire's library AWG | Warning |
| Part type | A part is used where its library type makes sense (for example, not a wire as a backshell) | Warning |
| Completeness | Missing part numbers, pins, duplicate IDs, unknown lengths, unused connectors/splices | Warning |
| Parts library | Parts that aren't in the library, or are missing the parameter a check needs (the check is skipped) | Info |
| Drawing format | Letter heights, required title-block fields, revision block vs. title block, parts list vs. balloons (ASME Y14) | Error / warning / info |

**Bundle diameter** at a connector counts every wire and cable that ends there (a cable or built-up shielded group
counts once, at its OD or at its members' bundle plus shield wall). It uses the common rule of thumb
*D ≈ 1.2 × √(Σ dᵢ²)*. Wire ODs come from the library, or are estimated from AWG for thin-wall wire, and the report says
when they were estimated. The calculated diameters are also added to the drawing notes.

### Lengths and quantities

- **Two-connector cable:** enter the overall length (sidebar or `--length`). **Harness with a breakout:** enter each
  connector's length to the breakout. **Splices** need *Near* and *Distance*. A per-wire **Length** overrides all of these.
  Lengths that can't be worked out show as **AR** (as required) in the BOM.
- Connectors, backshells, boots and labels are 1 per connector end. **Contacts** are 1 per pin used (wires plus shield
  drains), except for connectors supplied with their contacts. Wire markers and wire heatshrink are 2 per wire. Shield terminations are 1 per terminated shield end.
  Cables and braid are counted by length. Parts with the same P/N are combined into one BOM item.

### DXF output

One AutoCAD R12 ASCII DXF per sheet, at true size in inches, with layers BORDER, TITLE_BLOCK, ASSEMBLY, CABLE, WIRING,
SHIELDS, FACE_VIEWS, TABLES and NOTES. Dashed lines use the DASHED line type. R12 opens in AutoCAD, SolidWorks, Inventor, Creo,
DraftSight, LibreCAD, QCAD and most other CAD programs.

The part numbers and parameters in the samples are illustrative examples (D38999 / MS3126 connectors, M39029
contacts, M85049 backshells, M22759 wire, M27500 cable, M81824 splices). Check every part number and value against
your own design, datasheets, and approved parts list.

### Privacy

Everything runs on your computer. The desktop app and CLI make no network connections, and
`.streamlit/config.toml` makes the web app listen only on `localhost` with Streamlit's usage statistics off.

### Example output

`examples/` holds the drawing package generated from the W101 sample (`samples/cable_*.csv` plus
`samples/parts_library.csv`): `W101-001.pdf`, one DXF per sheet in `examples/dxf/`, and the design rule check report
`W101-001_drc.csv`.

## Building the installers

```powershell
.\packaging\build.ps1          # Windows: dist\CableDesigner.exe (+ installer if Inno Setup 6 is installed)
```

```bash
./packaging/build.sh            # macOS: dist/CableDesigner.app   Linux: dist/CableDesigner
```

Both scripts run the packaged app's `--smoke-test` (it opens a sample and exports a full package) before finishing.
The GitHub Actions workflow runs the tests on every push. Pushing a version tag (`git tag v0.3.0 && git push --tags`), or running the workflow by hand from the Actions tab with a version,
builds the Windows installer and executable and the macOS app, smoke-tests them, and attaches them to a GitHub release.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
