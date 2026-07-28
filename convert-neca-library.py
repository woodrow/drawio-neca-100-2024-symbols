#!/usr/bin/env python3
"""Convert the public NECA 100-2024 DWG package into draw.io libraries."""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
import zlib

os.environ.setdefault(
    "XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "neca-ezdxf-cache")
)

try:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
    from ezdxf.addons.drawing.config import (
        BackgroundPolicy,
        ColorPolicy,
        Configuration,
        LineweightPolicy,
    )
except ImportError as error:
    raise SystemExit(
        "Missing Python dependencies. Install them with:\n"
        "  python3 -m pip install -r requirements-neca.txt"
    ) from error


SOURCE_ROOT_NAME = "NECA 100-2024 Symbols"
OUTPUT_DIR_NAME = "neca-100-2024"
COMBINED_LIBRARY_NAME = "neca-100-2024-drawio-all.xml"

CATEGORY_FILENAMES = {
    "1.0 Wiring Methods": "01-wiring-methods.xml",
    "2.0 Luminaire Fixtures": "02-luminaire-fixtures.xml",
    "3.0 Outlets & Receptacles": "03-outlets-receptacles.xml",
    "4.0 Switches & Sensors": "04-switches-sensors.xml",
    "5.0 Motors-Controls": "05-motors-controls.xml",
    "6.0 Security": "06-security.xml",
    "7.0 Fire Alarm Communications & Panels": "07-fire-alarm.xml",
    "8.0 Power Distribution Equipment": "08-power-distribution.xml",
    "9.0 Communications-Teldata": "09-communications-teledata.xml",
    "10.0 Site Work": "10-site-work.xml",
    "11.0 Schematic Fault Circuit Interrupter, Personal Protection":
        "11-schematic-one-line.xml",
    "12.0 Miscellaneous": "12-miscellaneous.xml",
    "13.0 Abbreviations": "13-abbreviations.xml",
    "14.0 Nurse Call System": "14-nurse-call.xml",
    "NFPA Alternate Fire Safety Symbols": "15-nfpa-alternate-fire-safety.xml",
    "One-Line Riser Diagrams": "16-one-line-riser-diagrams.xml",
    "Schedules": "17-schedules.xml",
}

PLACEHOLDER_PATTERN = re.compile(r"[xXzZ?#%]")
SVG_VIEWBOX_PATTERN = re.compile(
    r'viewBox="[^"]*?\s([0-9.+-]+)\s([0-9.+-]+)"'
)
SVG_STROKE_PATTERN = re.compile(r"stroke-width:\s*[^;]+;")
SVG_PATH_TOKEN_PATTERN = re.compile(
    r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)
SVG_CSS_RULE_PATTERN = re.compile(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}")


def natural_key(value: str) -> list[object]:
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    ]


def attribute_is_symbol_modifier(text: str) -> bool:
    """Keep short literal modifiers; omit prompted project data."""
    value = text.strip()
    return bool(value) and len(value) <= 6 and not PLACEHOLDER_PATTERN.search(value)


def locate_source_root(source: Path, temporary_root: Path) -> Path:
    if source.is_file():
        if not zipfile.is_zipfile(source):
            raise ValueError(f"Not a ZIP archive: {source}")
        with zipfile.ZipFile(source) as archive:
            safe_members = [
                member
                for member in archive.infolist()
                if not member.filename.startswith("__MACOSX/")
                and ".." not in Path(member.filename).parts
            ]
            archive.extractall(temporary_root, members=safe_members)
        root = temporary_root / SOURCE_ROOT_NAME
    else:
        direct = source / SOURCE_ROOT_NAME
        root = direct if direct.is_dir() else source

    if not root.is_dir():
        raise ValueError(
            f"Could not find the '{SOURCE_ROOT_NAME}' directory in {source}"
        )
    return root


def convert_dwg_to_dxf(dwg_path: Path, dxf_path: Path) -> list[str]:
    result = subprocess.run(
        [
            "dwg2dxf",
            "--force-free",
            "--overwrite",
            "--file",
            str(dxf_path),
            str(dwg_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not dxf_path.exists():
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"dwg2dxf failed for {dwg_path}: {detail}")
    return [
        line.strip()
        for line in result.stderr.splitlines()
        if line.strip()
    ]


def clean_attributes(modelspace) -> tuple[list[str], list[str]]:
    retained: list[str] = []
    omitted: list[str] = []

    for entity in list(modelspace):
        if entity.dxftype() not in {"ATTDEF", "ATTRIB"}:
            continue
        value = str(entity.dxf.get("text", "")).strip()
        tag = str(entity.dxf.get("tag", "")).strip()
        description = f"{tag}={value}" if tag else value
        if attribute_is_symbol_modifier(value):
            retained.append(description)
        else:
            omitted.append(description)
            modelspace.delete_entity(entity)

    return sorted(set(retained)), sorted(set(omitted))


def render_degenerate_line_svg(modelspace) -> str | None:
    """Render zero-height/zero-width line-only drawings missed by SVGBackend."""
    lines = list(modelspace.query("LINE"))
    if len(lines) != 1 or len(modelspace) != 1:
        return None

    line = lines[0]
    start = line.dxf.start
    end = line.dxf.end
    dx = abs(end.x - start.x)
    dy = abs(end.y - start.y)
    linetype = str(line.dxf.get("linetype", "")).upper()
    dash = (
        ' stroke-dasharray="24 14"'
        if linetype not in {"", "BYBLOCK", "BYLAYER", "CONTINUOUS"}
        else ""
    )

    if dx >= dy:
        view_box = "0 0 1000 100"
        coordinates = 'x1="0" y1="50" x2="1000" y2="50"'
    else:
        view_box = "0 0 100 1000"
        coordinates = 'x1="50" y1="0" x2="50" y2="1000"'

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}">'
        f'<line {coordinates} stroke="#000000" stroke-width="1.5" '
        f'vector-effect="non-scaling-stroke"{dash}/></svg>'
    )


def repair_missing_block_references(document) -> list[str]:
    notes: list[str] = []
    available = {block.name for block in document.blocks}

    for block in document.blocks:
        for entity in list(block):
            if entity.dxftype() != "INSERT":
                continue
            name = str(entity.dxf.name)
            if name in available:
                continue
            candidates = sorted(
                candidate
                for candidate in available
                if candidate.startswith(name) or name.startswith(candidate)
            )
            if len(candidates) == 1:
                entity.dxf.name = candidates[0]
                notes.append(f"repaired block reference {name} -> {candidates[0]}")
            else:
                block.delete_entity(entity)
                notes.append(f"omitted unresolved block reference {name}")
    return notes


def render_svg(
    dxf_path: Path,
) -> tuple[str, list[str], list[str], list[str]]:
    document = ezdxf.readfile(dxf_path)
    repair_notes = repair_missing_block_references(document)
    modelspace = document.modelspace()
    retained, omitted = clean_attributes(modelspace)

    backend = svg.SVGBackend()
    config = Configuration(
        color_policy=ColorPolicy.BLACK,
        background_policy=BackgroundPolicy.OFF,
        lineweight_policy=LineweightPolicy.RELATIVE_FIXED,
    )
    Frontend(RenderContext(document), backend, config=config).draw_layout(modelspace)
    svg_text = backend.get_string(layout.Page(0, 0))
    svg_text = re.sub(r"^<\?xml[^>]*>\s*", "", svg_text)
    if svg_text.strip() == "<svg />":
        svg_text = render_degenerate_line_svg(modelspace) or svg_text

    # Keep linework readable at both sidebar-thumbnail and drawing scales.
    svg_text = SVG_STROKE_PATTERN.sub(
        "stroke-width: 1.5; vector-effect: non-scaling-stroke;",
        svg_text,
    )
    return svg_text, retained, omitted, repair_notes


def svg_dimensions(svg_text: str) -> tuple[int, int]:
    match = SVG_VIEWBOX_PATTERN.search(svg_text)
    if match is None:
        return 64, 64
    width = max(float(match.group(1)), 1.0)
    height = max(float(match.group(2)), 1.0)
    aspect = width / height
    maximum = 72
    minimum = 10
    if aspect >= 1:
        return maximum, max(minimum, round(maximum / aspect))
    return max(minimum, round(maximum * aspect)), maximum


def format_stencil_number(value: float) -> str:
    value = 0.0 if abs(value) < 0.0000005 else value
    return f"{value:.5f}".rstrip("0").rstrip(".")


def svg_path_to_stencil(
    path_data: str,
    view_x: float,
    view_y: float,
    view_width: float,
    view_height: float,
) -> ET.Element:
    tokens = SVG_PATH_TOKEN_PATTERN.findall(path_data)
    path = ET.Element("path")
    current_x = 0.0
    current_y = 0.0
    start_x = 0.0
    start_y = 0.0
    command = ""
    index = 0

    def normalized(x: float, y: float) -> tuple[str, str]:
        return (
            format_stencil_number((x - view_x) / view_width * 100.0),
            format_stencil_number((y - view_y) / view_height * 100.0),
        )

    def available_numbers(count: int) -> bool:
        return (
            index + count <= len(tokens)
            and all(not token.isalpha() for token in tokens[index:index + count])
        )

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command in {"Z", "z"}:
                ET.SubElement(path, "close")
                current_x, current_y = start_x, start_y
                continue

        if command in {"M", "m"}:
            first = True
            while available_numbers(2):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if command == "m":
                    x += current_x
                    y += current_y
                current_x, current_y = x, y
                x_value, y_value = normalized(x, y)
                ET.SubElement(
                    path,
                    "move" if first else "line",
                    {"x": x_value, "y": y_value},
                )
                if first:
                    start_x, start_y = x, y
                    first = False
            command = "l" if command == "m" else "L"
        elif command in {"L", "l"}:
            while available_numbers(2):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if command == "l":
                    x += current_x
                    y += current_y
                current_x, current_y = x, y
                x_value, y_value = normalized(x, y)
                ET.SubElement(path, "line", {"x": x_value, "y": y_value})
        elif command in {"C", "c"}:
            while available_numbers(6):
                values = [float(token) for token in tokens[index:index + 6]]
                index += 6
                if command == "c":
                    values = [
                        values[0] + current_x,
                        values[1] + current_y,
                        values[2] + current_x,
                        values[3] + current_y,
                        values[4] + current_x,
                        values[5] + current_y,
                    ]
                x1, y1 = normalized(values[0], values[1])
                x2, y2 = normalized(values[2], values[3])
                x3, y3 = normalized(values[4], values[5])
                ET.SubElement(
                    path,
                    "curve",
                    {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "x3": x3, "y3": y3},
                )
                current_x, current_y = values[4], values[5]
        elif command in {"Q", "q"}:
            while available_numbers(4):
                values = [float(token) for token in tokens[index:index + 4]]
                index += 4
                if command == "q":
                    values = [
                        values[0] + current_x,
                        values[1] + current_y,
                        values[2] + current_x,
                        values[3] + current_y,
                    ]
                x1, y1 = normalized(values[0], values[1])
                x2, y2 = normalized(values[2], values[3])
                ET.SubElement(
                    path,
                    "quad",
                    {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                )
                current_x, current_y = values[2], values[3]
        else:
            raise ValueError(f"Unsupported SVG path command: {command!r}")

    return path


def svg_class_paints(svg_root: ET.Element) -> dict[str, tuple[bool, bool]]:
    result: dict[str, tuple[bool, bool]] = {}
    for element in svg_root.iter():
        if element.tag.rsplit("}", 1)[-1] != "style":
            continue
        for class_name, declarations in SVG_CSS_RULE_PATTERN.findall(element.text or ""):
            properties = {}
            for declaration in declarations.split(";"):
                if ":" in declaration:
                    key, value = declaration.split(":", 1)
                    properties[key.strip()] = value.strip()
            result[class_name] = (
                properties.get("stroke", "none") != "none",
                properties.get("fill", "none") != "none",
            )
    return result


def svg_to_stencil(svg_text: str) -> str:
    svg_root = ET.fromstring(svg_text)
    view_box = [float(value) for value in svg_root.attrib["viewBox"].split()]
    if len(view_box) != 4:
        raise ValueError(f"Invalid SVG viewBox: {svg_root.attrib['viewBox']}")
    view_x, view_y, view_width, view_height = view_box
    view_width = max(view_width, 1.0)
    view_height = max(view_height, 1.0)
    paints = svg_class_paints(svg_root)

    shape = ET.Element(
        "shape",
        {
            "name": "NECA symbol",
            "w": "100",
            "h": "100",
            "aspect": "variable",
            "strokewidth": "inherit",
        },
    )
    foreground = ET.SubElement(shape, "foreground")
    ET.SubElement(foreground, "linejoin", {"join": "round"})
    ET.SubElement(foreground, "linecap", {"cap": "round"})
    geometry_count = 0

    for element in svg_root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "path":
            class_name = element.attrib.get("class", "")
            stroke, fill = paints.get(class_name, (True, False))
            foreground.append(
                svg_path_to_stencil(
                    element.attrib["d"],
                    view_x,
                    view_y,
                    view_width,
                    view_height,
                )
            )
            if stroke and fill:
                ET.SubElement(foreground, "fillstroke")
            elif fill:
                ET.SubElement(foreground, "fill")
            else:
                ET.SubElement(foreground, "stroke")
            geometry_count += 1
        elif tag == "line":
            dashed = "stroke-dasharray" in element.attrib
            if dashed:
                ET.SubElement(foreground, "save")
                ET.SubElement(foreground, "dashed", {"dashed": "1"})
            line_path = ET.SubElement(foreground, "path")
            x1 = (float(element.attrib["x1"]) - view_x) / view_width * 100.0
            y1 = (float(element.attrib["y1"]) - view_y) / view_height * 100.0
            x2 = (float(element.attrib["x2"]) - view_x) / view_width * 100.0
            y2 = (float(element.attrib["y2"]) - view_y) / view_height * 100.0
            ET.SubElement(
                line_path,
                "move",
                {"x": format_stencil_number(x1), "y": format_stencil_number(y1)},
            )
            ET.SubElement(
                line_path,
                "line",
                {"x": format_stencil_number(x2), "y": format_stencil_number(y2)},
            )
            ET.SubElement(foreground, "stroke")
            if dashed:
                ET.SubElement(foreground, "restore")
            geometry_count += 1

    if geometry_count == 0:
        raise ValueError("SVG contains no drawable paths")
    return ET.tostring(shape, encoding="unicode", short_empty_elements=True)


def compress_drawio_stencil(stencil_xml: str) -> str:
    encoded = urllib.parse.quote(stencil_xml, safe="~()*!.'-_").encode("ascii")
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(encoded) + compressor.flush()
    return base64.b64encode(compressed).decode("ascii")


def drawio_entry(svg_text: str, title: str) -> dict[str, object]:
    width, height = svg_dimensions(svg_text)
    stencil = compress_drawio_stencil(svg_to_stencil(svg_text))
    style = (
        f"shape=stencil({stencil});aspect=fixed;whiteSpace=wrap;html=1;"
        "strokeColor=#000000;fillColor=#000000;resizable=1;rotatable=1;"
    )
    model = ET.Element("mxGraphModel")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": "2",
            "value": "",
            "style": style,
            "vertex": "1",
            "parent": "1",
        },
    )
    ET.SubElement(
        cell,
        "mxGeometry",
        {"width": str(width), "height": str(height), "as": "geometry"},
    )
    return {
        "xml": ET.tostring(model, encoding="unicode", short_empty_elements=True),
        "w": width,
        "h": height,
        "title": title,
    }


def write_library(path: Path, title: str, entries: list[dict[str, object]]) -> None:
    payload = html.escape(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
        quote=False,
    )
    title_attribute = html.escape(title, quote=True)
    tags = (
        "NECA 100 2024 electrical architecture construction CAD "
        "receptacle lighting switch fire alarm low voltage"
    )
    path.write_text(
        f'<mxlibrary title="{title_attribute}" tags="{tags}">'
        f"{payload}</mxlibrary>\n",
        encoding="utf-8",
    )


def source_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.rglob("*.dwg")
        if "__MACOSX" not in path.parts and not path.name.startswith("._")
    ]
    return sorted(files, key=lambda path: natural_key(str(path.relative_to(root))))


def convert(source: Path, output_dir: Path) -> None:
    if shutil.which("dwg2dxf") is None:
        raise SystemExit(
            "dwg2dxf was not found. Install GNU LibreDWG first "
            "(for example: brew install libredwg)."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    all_entries: list[dict[str, object]] = []
    entries_by_category: dict[str, list[dict[str, object]]] = {}
    manifest_rows: list[dict[str, str]] = []
    conversion_warnings: dict[str, list[str]] = {}

    with tempfile.TemporaryDirectory(prefix="neca-100-convert-") as temporary:
        temporary_root = Path(temporary)
        root = locate_source_root(source, temporary_root / "source")
        dxf_root = temporary_root / "dxf"
        files = source_files(root)
        print(f"Converting {len(files)} NECA DWG files...")

        for index, dwg_path in enumerate(files, start=1):
            relative = dwg_path.relative_to(root)
            category = relative.parts[0] if len(relative.parts) > 1 else "Uncategorized"
            symbol_id = dwg_path.stem
            dxf_path = dxf_root / relative.with_suffix(".dxf")
            dxf_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                warnings = convert_dwg_to_dxf(dwg_path, dxf_path)
                svg_text, retained, omitted, repair_notes = render_svg(dxf_path)
                warnings.extend(repair_notes)
            except Exception as error:
                raise RuntimeError(f"{relative}: {error}") from error
            title = f"{category} — {symbol_id}"
            entry = drawio_entry(svg_text, title)
            all_entries.append(entry)
            entries_by_category.setdefault(category, []).append(entry)

            manifest_rows.append(
                {
                    "category": category,
                    "symbol_id": symbol_id,
                    "source_dwg": str(relative),
                    "library_title": title,
                    "retained_attributes": "; ".join(retained),
                    "omitted_attributes": "; ".join(omitted),
                }
            )
            if warnings:
                conversion_warnings[str(relative)] = warnings
            if index % 50 == 0 or index == len(files):
                print(f"  {index}/{len(files)}")

    write_library(
        output_dir / COMBINED_LIBRARY_NAME,
        "NECA 100-2024 — Complete",
        all_entries,
    )

    for category, entries in sorted(
        entries_by_category.items(), key=lambda item: natural_key(item[0])
    ):
        filename = CATEGORY_FILENAMES.get(
            category,
            re.sub(r"[^a-z0-9]+", "-", category.casefold()).strip("-") + ".xml",
        )
        write_library(
            output_dir / filename,
            f"NECA 100-2024 — {category}",
            entries,
        )

    with (output_dir / "manifest.csv").open(
        "w", encoding="utf-8", newline=""
    ) as manifest_file:
        writer = csv.DictWriter(
            manifest_file,
            fieldnames=[
                "category",
                "symbol_id",
                "source_dwg",
                "library_title",
                "retained_attributes",
                "omitted_attributes",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    (output_dir / "conversion-warnings.json").write_text(
        json.dumps(conversion_warnings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(all_entries)} symbols across "
        f"{len(entries_by_category)} categories to {output_dir}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        help="NECA ZIP archive or extracted source directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / OUTPUT_DIR_NAME,
        help=f"Output directory (default: {OUTPUT_DIR_NAME})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        convert(args.source.expanduser().resolve(), args.output.resolve())
    except (OSError, ValueError, RuntimeError, ezdxf.DXFError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
