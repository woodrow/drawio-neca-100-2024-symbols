# NECA 100-2024 symbols for draw.io

This project converts the publicly downloadable **NECA 100-2024 CAD Symbols**
package from DWG into draw.io/diagrams.net custom libraries.

The generated set contains 396 vector entries across the complete source
package:

- Wiring methods
- Luminaires
- Outlets and receptacles
- Switches and sensors
- Motors and controls
- Security
- Fire alarm communications and panels
- Power distribution equipment
- Communications / tele-data
- Site work
- Schematic and one-line symbols
- Miscellaneous symbols
- Abbreviations
- Nurse call
- NFPA alternate fire-safety symbols
- Riser diagrams and schedules

## Use the libraries

For the complete set, open:

`neca-100-2024/neca-100-2024-drawio-all.xml`

Smaller category libraries are also available in the same directory. In
draw.io or diagrams.net:

1. Select **File → Open Library From → Device**.
2. Choose the complete library or one of the category `.xml` files.
3. Drag a symbol from the sidebar onto the drawing.

Symbols are embedded as scalable SVG vectors with a fixed aspect ratio. Their
SVG style rules use an explicit `light-dark(#000000, #ffffff)` colour pair, so
library thumbnails and inserted shapes use black linework in light mode and
white linework in dark mode. Each embedded SVG explicitly supports both colour
schemes so this also works while the symbol is still a sidebar thumbnail. The
same rules are exposed through
`editableCssRules`, so line and fill colours appear in the normal
**Format → Style** colour controls. Short device modifiers such as `F`, `WP`,
`SD`, and `MCC` are preserved. Prompted, project-specific AutoCAD
attributes—panel/circuit number, amperage, horsepower, drawing number, and
similar placeholders—are intentionally omitted.

`neca-100-2024/manifest.csv` maps every entry back to its source DWG and records
which attributes were retained or omitted.

## Regenerate

Requirements:

- `dwg2dxf` from [GNU LibreDWG](https://www.gnu.org/software/libredwg/)
- Python 3.10 or newer
- Python packages in `requirements-neca.txt`

On macOS with Homebrew:

```sh
brew install libredwg
python3 -m venv .venv
.venv/bin/pip install -r requirements-neca.txt
.venv/bin/python convert-neca-library.py /path/to/NECA-100-2024-Symbols.zip
```

The converter accepts either the downloaded ZIP or its extracted top-level
folder.

## Source and rights

Source: [NECA 100-2024 CAD Symbols Download](https://www.necanet.org/topics/codesandstandards/neis/neis-100---cad-symbols-download).

The source CAD files and NECA 100 standard are © National Electrical
Contractors Association. This is an unofficial format conversion and is not
endorsed by NECA. The original DWG archive is not included in this repository.
Review the source publisher's terms before redistributing converted assets.

Built with [Codex](https://openai.com/codex/).
