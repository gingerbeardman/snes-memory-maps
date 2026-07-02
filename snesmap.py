#!/usr/bin/env python3
"""Shared implementation for the rommap.py and rammap.py command-line tools.

Run one of the public entry points rather than invoking this file directly.
"""
import argparse
import colorsys
import csv
import html
import os
import re

__version__ = "1.0.0"

ROOT = os.getcwd()
DEFAULT_MAP_KIND = os.environ.get("SNES_MEMORY_MAP_KIND", "rom")
DESCRIPTION = (
    "Generate an SNES WRAM CSV/SVG map from an ld.lld or vlink linker map."
    if DEFAULT_MAP_KIND == "ram"
    else "Generate an SNES ROM CSV/SVG map from an ld.lld or vlink linker map."
)
parser = argparse.ArgumentParser(
    prog=os.environ.get("SNES_MEMORY_MAP_PROGRAM"),
    description=DESCRIPTION,
)
parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
parser.add_argument("map", nargs="?", default=os.path.join(ROOT, "build", "game.map"))
parser.add_argument("--format", choices=("auto", "lld", "vlink"), default="auto")
if DEFAULT_MAP_KIND == "rom":
    parser.add_argument("--linker-script", default=os.path.join(ROOT, "game.ld"))
else:
    parser.set_defaults(linker_script=os.path.join(ROOT, "game.ld"))
parser.add_argument("-o", "--output-prefix",
                    help="output prefix (default: build/rommap or build/rammap)")
parser.add_argument("--compiler", help="compiler/linker label embedded in the SVG")
parser.add_argument("--colour-key", "--color-key", action="store_true",
                    help="show colour legends in both SVGs (default: off)")
parser.add_argument("--checkerboard", action="store_true",
                    help="draw checkerboard in free space (default: transparent)")
parser.add_argument("--coloured-percentages", "--colored-percentages", action="store_true",
                    help="colour percentages amber/red near capacity (default: off)")
parser.add_argument("--map-kind", choices=("rom", "ram"), default=DEFAULT_MAP_KIND,
                    help=argparse.SUPPRESS)
args = parser.parse_args()

MAP = os.path.abspath(args.map)
LD = os.path.abspath(args.linker_script)
MAP_KIND = args.map_kind
TOOL_NAME = f"{MAP_KIND}map.py"
default_prefix = os.path.join(ROOT, "build", f"{MAP_KIND}map")
OUTPUT_PREFIX = args.output_prefix or default_prefix
CSV_OUT = os.path.abspath(OUTPUT_PREFIX + ".csv")
SVG_OUT = os.path.abspath(OUTPUT_PREFIX + ".svg")
SHOW_COLOUR_KEY = args.colour_key
SHOW_CHECKERBOARD = args.checkerboard
SHOW_COLOURED_PERCENTAGES = args.coloured_percentages

RAM_REGIONS = [
    ("direct_page", 0x000000, 0x0100),
    ("low_wram",    0x000100, 0x1f00),
    ("bank_7e",     0x7e2000, 0xe000),
    ("bank_7f",     0x7f0000, 0x10000),
]
RAM_COLORS = {
    "data": "#3f8edb",
    "bss": "#70b85a",
    "noinit": "#a56bd4",
    "stack": "#e69a3a",
    "compiler": "#d85c68",
    "allocated": "#45b8ad",
}

def load_regions(ld_path):
    """Parse `name (attrs) : ORIGIN = 0x.., LENGTH = 0x..` from the MEMORY{} block.
    Keep ROM-located regions; skip low WRAM and banks $7E/$7F. Robust to comments."""
    txt = open(ld_path).read()
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)   # strip comments first
    mem = re.search(r"MEMORY\s*\{(.*?)\n\}", txt, re.S)
    body = mem.group(1) if mem else txt
    rx = re.compile(r"^\s*(\w+)\s*\([^)]*\)\s*:\s*ORIGIN\s*=\s*(0x[0-9a-fA-F]+)\s*,"
                    r"\s*LENGTH\s*=\s*(0x[0-9a-fA-F]+)", re.M)
    out = []
    for name, o, l in rx.findall(body):
        origin = int(o, 16)
        if origin < 0x8000 or origin >> 16 in (0x7e, 0x7f):
            continue
        out.append((name, origin, int(l, 16)))
    return out

def region_of(addr, regions):
    for name, o, l in regions:
        if o <= addr < o + l:
            return name
    return None

# input lines:  <vma> <lma> <size> <align>  <file>:(<section>)   OR  <vma> ... <symbol>
line_re = re.compile(
    r"^\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\d+\s+(\S.*)$")
# a "lumped" section holds many symbols under ONE name (art -> .rodata.bankN, render ->
# .text.bankN, movers -> .text.bank8). Capturing the container hides everything inside it
# as one blob called "bankN"; instead we expand it into its nested per-symbol lines.
lump_re = re.compile(r":\(\.(?:text|rodata|data)\.bank\d+\)$")
sym_line_re = re.compile(r"^[A-Za-z_]\w*$")            # a nested C symbol (no ':' , no '.')
vlink_input_re = re.compile(
    r"^\s+([0-9a-fA-F]{8})\s+-\s+([0-9a-fA-F]{8})\s+.+?\(([^()]*)\)\s*$")
vlink_symbol_re = re.compile(
    r"^\d+_(?:text|rodata|data|bss|ndata|nbss|fdata|fbss)"
    r"(?:\.(?:far|near))?\.(.+?)(?:\.\d+)?$")
ram_input_re = re.compile(r":\(\.([^()]*)\)$")

def parse_lld(text, regions):
    rows = []
    seen = set()
    expand_reg = None
    for ln in text.splitlines():
        m = line_re.match(ln)
        if not m:
            continue
        vma = int(m.group(1), 16); size = int(m.group(3), 16); name = m.group(4).strip()
        if size == 0 or "=" in name or name.startswith("0x"):
            continue
        reg = region_of(vma, regions)
        if not reg:
            continue
        mm = re.search(r":\(\.(?:text|rodata|data)(?:\.([A-Za-z0-9_]+))?\)", name)
        if mm:
            # an input line "file.o:(.section[.sym])".
            if lump_re.search(name):
                # a lumped bankN section: DON'T count the blob; expand its children below.
                expand_reg = reg
                continue
            expand_reg = None          # a normal per-function section -> count it as a leaf
            sym = mm.group(1) or name.split(":")[-1]
        elif expand_reg == reg and sym_line_re.match(name):
            # a nested symbol line inside the lumped section we're expanding.
            sym = name
        else:
            # section/output line, or a nested symbol under a per-function section
            # (already counted via its container) -> skip, and end any expansion run.
            if reg != expand_reg:
                expand_reg = None
            continue
        key = (vma, size)
        if key in seen:
            continue
        seen.add(key)
        rows.append((reg, vma, size, sym))
    return rows

def ram_region_address(address):
    """Canonicalize a bank-$7E low-WRAM address to the linker's common 16-bit form."""
    if 0x7e0000 <= address < 0x7e2000:
        return address & 0xffff
    return address

def physical_ram_address(address):
    """Present low WRAM using its unambiguous native bank-$7E address."""
    return 0x7e0000 | address if address < 0x2000 else address

def parse_lld_ram(text):
    """Extract allocated data leaves from an ld.lld map without double counting."""
    rows = []
    seen = set()
    for line in text.splitlines():
        match = line_re.match(line)
        if not match:
            continue
        address = ram_region_address(int(match.group(1), 16))
        size = int(match.group(3), 16)
        source = match.group(4).strip()
        if size <= 0 or "=" in source or source.startswith("<internal>:"):
            continue
        section_match = ram_input_re.search(source)
        if not section_match:
            continue
        region = region_of(address, RAM_REGIONS)
        if not region:
            continue
        section = section_match.group(1)
        if section.startswith(("zp.data", "data", "bank_7e_data")):
            allocation = "data"
        elif section.startswith(("zp.bss", "bss", "bank_7e_bss")):
            allocation = "bss"
        elif section.startswith("noinit"):
            allocation = "noinit"
        else:
            allocation = "allocated"
        suffix = None
        for prefix in ("bank_7e_data", "bank_7e_bss", "zp.data", "zp.bss",
                       "data", "bss", "noinit"):
            if section.startswith(prefix + "."):
                suffix = section[len(prefix) + 1:].lstrip(".")
                break
        if suffix is None:
            object_name = os.path.basename(source.split(":(", 1)[0])
            symbol = f"{object_name}:{section}"
        else:
            symbol = suffix
            if symbol.startswith("Lstatic_"):
                symbol = symbol[1:]
        key = (address, size)
        if key in seen:
            continue
        seen.add(key)
        rows.append((region, address, size, symbol, allocation))
    return rows

def add_inferred_ram_reservations(text, entries):
    """Add linker-declared direct-page registers and the page-$01 hardware stack.

    These are not input sections, so link maps otherwise report them as apparently
    free. They are only added when the corresponding linker symbols are present.
    """
    rows = list(entries)
    rc_numbers = [int(number) for number in re.findall(r"\b__rc(\d+)\s*=", text)]
    if 0 in rc_numbers:
        size = min(0x100, max(rc_numbers) + 1)
        rows.append(("direct_page", 0, size, "compiler direct-page registers", "compiler"))

    stack_match = re.search(r"\b__stack\s*=\s*(0x[0-9a-fA-F]+|\d+)", text)
    if stack_match:
        stack_top = int(stack_match.group(1), 0)
        if 0x100 < stack_top <= 0x200:
            rows.append(("low_wram", 0x100, stack_top - 0x100,
                         "hardware stack (reserved)", "stack"))
    return rows

def parse_vlink(text, regions, address_mapper=None):
    rows = []
    in_mapping = False
    for line in text.splitlines():
        if line.startswith("Section mapping (numbers in hex):"):
            in_mapping = True
            continue
        if in_mapping and line.startswith("Symbols of "):
            break
        if not in_mapping:
            continue
        match = vlink_input_re.match(line)
        if not match:
            continue
        start, end = int(match.group(1), 16), int(match.group(2), 16)
        original_start = start
        if address_mapper:
            start = address_mapper(start)
            if start is None:
                continue
        region = region_of(start, regions)
        size = end - original_start
        if size <= 0 or not region:
            continue
        section = match.group(3)
        symbol_match = vlink_symbol_re.match(section)
        symbol = symbol_match.group(1) if symbol_match else section.lstrip(".")
        if symbol == "start_text.startup":
            symbol = "startup"
        rows.append((region, start, size, symbol))
    return rows

def hirom_physical_address(address):
    """Map vlink-hi CPU addresses to 32 KiB physical-ROM chunks.

    vlink-hi emits the $40:0000 xrom first, the $00:8000 header bank second,
    then full 64 KiB HiROM banks beginning at $41:0000.
    """
    if 0x400000 <= address < 0x408000:
        offset = address - 0x400000
    elif 0x008000 <= address < 0x010000:
        offset = 0x8000 + address - 0x008000
    elif 0x410000 <= address < 0x800000:
        offset = 0x10000 + address - 0x410000
    else:
        return None
    bank, within = divmod(offset, 0x8000)
    return (bank << 16) | 0x8000 | within

with open(MAP, encoding="utf-8", errors="replace") as stream:
    map_text = stream.read()
if args.format == "auto":
    MAP_FORMAT = "vlink" if "Section mapping (numbers in hex):" in map_text else "lld"
else:
    MAP_FORMAT = args.format

if MAP_FORMAT == "vlink":
    REGIONS = [(f"bank_{bank:02x}", (bank << 16) | 0x8000, 0x8000)
               for bank in range(16)]
    is_hirom = bool(re.search(r"^\s+00400000\s+-", map_text, re.M))
    rows = parse_vlink(map_text, REGIONS,
                       hirom_physical_address if is_hirom else None)
    ram_rows = [
        (region, address, size, symbol, "allocated")
        for region, address, size, symbol
        in parse_vlink(map_text, RAM_REGIONS, ram_region_address)
    ]
    COMPILER_LABEL = args.compiler or "vbcc65816/vlink"
else:
    if MAP_KIND == "rom":
        REGIONS = load_regions(LD)
        rows = parse_lld(map_text, REGIONS)
    else:
        REGIONS = []
        rows = []
    ram_rows = parse_lld_ram(map_text)
    COMPILER_LABEL = args.compiler or "llvm-mos/ld.lld"

if MAP_KIND == "rom" and not rows:
    parser.error(f"no ROM symbols found in {MAP} as {MAP_FORMAT}")

ram_rows = add_inferred_ram_reservations(map_text, ram_rows)
if MAP_KIND == "ram" and not ram_rows:
    parser.error(f"no WRAM allocations found in {MAP} as {MAP_FORMAT}")

rows.sort(key=lambda r: r[1])
ram_rows.sort(key=lambda r: r[1])
os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
with open(CSV_OUT, "w", newline="") as f:
    writer = csv.writer(f)
    if MAP_KIND == "rom":
        writer.writerow(["region", "addr_start", "addr_end", "size", "symbol"])
        for region, address, size, symbol in rows:
            writer.writerow([
                region,
                f"0x{address:06x}",
                f"0x{address + size - 1:06x}",
                size,
                symbol,
            ])
    else:
        writer.writerow(["region", "addr_start", "addr_end", "size", "allocation", "symbol"])
        for region, address, size, symbol, allocation in ram_rows:
            start = physical_ram_address(address)
            writer.writerow([
                region,
                f"0x{start:06x}",
                f"0x{start + size - 1:06x}",
                size,
                allocation,
                symbol,
            ])

def squarify(items, x, y, width, height):
    """Return (item, x, y, width, height) rectangles using a squarified layout."""
    items = [(item, float(size)) for item, size in items if size > 0]
    if not items or width <= 0 or height <= 0:
        return []

    scale = width * height / sum(size for _, size in items)
    remaining = [(item, size * scale) for item, size in items]
    out = []

    def worst_ratio(row, short_side):
        if not row:
            return float("inf")
        sizes = [size for _, size in row]
        total = sum(sizes)
        side2 = short_side * short_side
        return max(side2 * max(sizes) / (total * total),
                   total * total / (side2 * min(sizes)))

    def place(row, rx, ry, rw, rh):
        area = sum(size for _, size in row)
        if rw >= rh:
            row_width = area / rh
            cursor = ry
            for item, size in row:
                item_height = size / row_width
                out.append((item, rx, cursor, row_width, item_height))
                cursor += item_height
            return rx + row_width, ry, max(0.0, rw - row_width), rh

        row_height = area / rw
        cursor = rx
        for item, size in row:
            item_width = size / row_height
            out.append((item, cursor, ry, item_width, row_height))
            cursor += item_width
        return rx, ry + row_height, rw, max(0.0, rh - row_height)

    row = []
    while remaining:
        candidate = row + [remaining[0]]
        short_side = min(width, height)
        if row and worst_ratio(candidate, short_side) > worst_ratio(row, short_side):
            x, y, width, height = place(row, x, y, width, height)
            row = []
        else:
            row = candidate
            remaining.pop(0)
    if row:
        place(row, x, y, width, height)
    return out

def color_for_region(index):
    """A distinct, readable base color for one linker region."""
    hue = (0.58 + index * 0.61803398875) % 1.0
    red, green, blue = colorsys.hls_to_rgb(hue, 0.58, 0.68)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"

def vary_color(color, key):
    """Vary sibling rectangles slightly while retaining the region's hue."""
    red, green, blue = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    delta = ((sum(ord(ch) for ch in key) % 5) - 2) * 0.035
    red, green, blue = colorsys.hls_to_rgb(hue, min(0.72, max(0.43, lightness + delta)),
                                           saturation)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"

def text_color(color):
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#10131a" if luminance > 145 else "#ffffff"

def fitted_font_size(text, width, height, maximum=12.0):
    """Largest monospace font that keeps text on one line inside a rectangle."""
    if not text or width <= 1 or height <= 1:
        return 0.0
    horizontal = (width - min(8.0, width * 0.08)) / (len(text) * 0.6)
    vertical = height - min(4.0, height * 0.2)
    return max(0.0, min(maximum, horizontal, vertical))

def capacity_class(percent):
    if not SHOW_COLOURED_PERCENTAGES:
        return ""
    displayed_percent = round(percent, 1)
    if displayed_percent >= 90:
        return "capacity-critical"
    if displayed_percent >= 75:
        return "capacity-warning"
    return ""

def capacity_tspan(text, percent):
    class_name = capacity_class(percent)
    class_attr = f' class="{class_name}"' if class_name else ""
    return f"<tspan{class_attr}>{html.escape(text)}</tspan>"

def free_fill():
    return "url(#free-pattern)" if SHOW_CHECKERBOARD else "transparent"

def make_rom_svg(regions, entries):
    """Render 16 physical ROM banks and their contents as an SVG treemap."""
    # A 4:3 canvas matches the intended display aspect ratio of an SNES screen.
    canvas_width, canvas_height = 1200, 900
    map_x, map_y = 16, 62
    map_bottom = 856 if SHOW_COLOUR_KEY else 875
    map_width, map_height = canvas_width - 32, map_bottom - map_y
    container_padding = 6
    footer_y = 891 if SHOW_COLOUR_KEY else 896
    bank_size = 0x8000
    bank_count = 16
    bank_columns = 4
    bank_rows = bank_count // bank_columns
    bank_gap = 4
    bank_width = (map_width - bank_gap * (bank_columns - 1)) / bank_columns
    bank_height = (map_height - bank_gap * (bank_rows - 1)) / bank_rows

    region_info = {
        name: (origin, length, index)
        for index, (name, origin, length) in enumerate(regions)
    }
    by_bank = {bank: [] for bank in range(bank_count)}
    for region, address, size, symbol in entries:
        origin, _, index = region_info[region]
        by_bank[origin >> 16].append((region, symbol, address, size, index))

    # OUTPUT_FORMAT physically copies the fixed region into each CPU-code bank.
    fixed_entries = list(by_bank[0])
    fixed_entries = [entry for entry in fixed_entries if entry[0] == "rom_bank_fixed"]
    code_banks = {
        origin >> 16 for name, origin, _ in regions if name.startswith("code_bank_")
    }
    for bank in code_banks - {0}:
        for region, symbol, address, size, index in fixed_entries:
            physical_address = (bank << 16) | (address & 0xffff)
            by_bank[bank].append((region, symbol, physical_address, size, index))

    physical_used = sum(size for bank_entries in by_bank.values()
                        for _, _, _, size, _ in bank_entries)
    physical_percent = 100 * physical_used / (bank_count * bank_size)
    layout_note = "4×4 physical bank grid · $00–$0F in reading order"
    if fixed_entries:
        layout_note += " · fixed region shown in $00/$03/$08"

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {canvas_width} {canvas_height}" '
        'role="img" aria-labelledby="title description">',
        '<title id="title">SNES ROM MAP</title>',
        '<desc id="description">Sixteen equal cells represent the 32 KiB physical ROM '
        'banks from $00 through $0F. Each bank contains its symbols and free space.</desc>',
        '<defs>',
        '  <pattern id="free-pattern" width="16" height="16" patternUnits="userSpaceOnUse">',
        '    <rect width="16" height="16" class="free-checker-a"/>',
        '    <path d="M0 0h8v8H0zM8 8h8v8H8z" class="free-checker-b"/>',
        '  </pattern>',
        '</defs>',
        f'<rect width="{canvas_width}" height="{canvas_height}" class="background"/>',
        '<text x="16" y="29" class="title">SNES ROM MAP</text>',
        f'<text x="16" y="49" class="subtitle">{layout_note}</text>',
        f'<text x="{canvas_width - 16}" y="49" text-anchor="end" class="summary">'
        f'{bank_count * bank_size:,} physical bytes · {physical_used:,} used · '
        f'{capacity_tspan(f"{physical_percent:.1f}% full", physical_percent)}</text>',
        '<style>',
        '  :root { color-scheme: dark light; }',
        '  .background { fill: #10131a; }',
        '  .map-surround { fill: #343a44; }',
        '  .region-bg { fill: #080a0e; }',
        '  .free-checker-a { fill: #252b35; }',
        '  .free-checker-b { fill: #3a424f; }',
        '  .free-label { fill: #eef1f5; }',
        '  text { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; '
        'pointer-events: none; }',
        '  .title { fill: #f3f6fb; font: 700 20px system-ui, sans-serif; }',
        '  .summary { fill: #8f9baa; font-size: 11px; }',
        '  .subtitle { fill: #8f9baa; font-size: 11px; }',
        '  .capacity-warning, .capacity-critical { font-weight: 800; '
        'paint-order: stroke fill; stroke: #10131a; stroke-width: 1.4px; '
        'stroke-linejoin: round; }',
        '  .capacity-warning { fill: #ffd166; }',
        '  .capacity-critical { fill: #ff6b6b; }',
        '  .map-label { font-weight: 650; }',
        '  .region-border { stroke: #20242b; stroke-width: 1; '
        'vector-effect: non-scaling-stroke; }',
        '  .item { stroke: #10131a; stroke-width: 1; '
        'vector-effect: non-scaling-stroke; }',
        '  @media (prefers-color-scheme: light) {',
        '    .background { fill: #f5f5f5; }',
        '    .map-surround { fill: #d6d9de; }',
        '    .region-bg { fill: #ffffff; }',
        '    .free-checker-a { fill: #ffffff; }',
        '    .free-checker-b { fill: #cccccc; }',
        '    .free-label { fill: #202124; }',
        '    .title { fill: #15171a; }',
        '    .subtitle, .summary { fill: #59616d; }',
        '    .capacity-warning { fill: #9a6700; stroke: #ffffff; }',
        '    .capacity-critical { fill: #b42318; stroke: #ffffff; }',
        '    .region-border { stroke: #9da2aa; }',
        '    .item { stroke: #ffffff; }',
        '  }',
        '</style>',
        f'<rect class="map-surround" x="{map_x - container_padding}" '
        f'y="{map_y - container_padding}" '
        f'width="{map_width + 2 * container_padding}" '
        f'height="{map_height + 2 * container_padding}"/>',
    ]

    for bank in range(bank_count):
        x = map_x + (bank % bank_columns) * (bank_width + bank_gap)
        y = map_y + (bank // bank_columns) * (bank_height + bank_gap)
        width, height = bank_width, bank_height
        base = color_for_region(bank)
        header_height = 25.0
        content_y = y + header_height
        content_height = height - header_height
        bank_entries = by_bank[bank]
        used = sum(size for _, _, _, size, _ in bank_entries)
        free = max(0, bank_size - used)
        percent_full = 100 * used / bank_size
        title = f"${bank:02X} · {used:,}/{bank_size:,} B · {percent_full:.1f}% full"

        svg.append(f'<g><title>{html.escape(title)}</title>')
        svg.append(f'<rect class="region-border region-bg" x="{x:.2f}" y="{y:.2f}" '
                   f'width="{width:.2f}" height="{height:.2f}"/>')
        svg.append(f'<rect x="{x + 1.5:.2f}" y="{y + 1.5:.2f}" '
                   f'width="{max(0, width - 3):.2f}" height="{max(0, header_height - 1.5):.2f}" '
                   f'fill="{base}"/>')
        svg.append(f'<text x="{x + 7:.2f}" y="{y + header_height - 7:.2f}" '
                   f'class="map-label" font-size="12" fill="{text_color(base)}">'
                   f'{html.escape(f"${bank:02X} · {used:,} B")}</text>')
        svg.append(f'<text x="{x + width - 7:.2f}" y="{y + header_height - 7:.2f}" '
                   f'text-anchor="end" class="map-label" font-size="12" '
                   f'fill="{text_color(base)}">'
                   f'{capacity_tspan(f"{percent_full:.1f}% full", percent_full)}</text>')

        leaves = [
            (("symbol", symbol, address, size, region, index), size)
            for region, symbol, address, size, index in sorted(
                bank_entries, key=lambda entry: (-entry[3], entry[2]))
        ]
        if free:
            leaves.append((("free", "FREE", 0, free, "", bank), free))
        leaves.sort(key=lambda item: (-item[1], item[0][2]))

        for item, ix, iy, item_width, item_height in squarify(
                leaves, x + 1.5, content_y, max(0, width - 3), content_height):
            kind, symbol, address, size, region, color_index = item
            if kind == "free":
                fill = free_fill()
                foreground = "#eef1f5"
                label_class = "map-label free-label"
                tooltip = f"${bank:02X} free: {size:,} B"
            else:
                fill = vary_color(color_for_region(color_index), symbol)
                foreground = text_color(fill)
                label_class = "map-label"
                tooltip = f"{symbol} · ${address:06X} · {size:,} B · {region}"

            svg.append(f'<g><title>{html.escape(tooltip)}</title>')
            svg.append(f'<rect class="item" x="{ix:.2f}" y="{iy:.2f}" '
                       f'width="{item_width:.2f}" height="{item_height:.2f}" '
                       f'fill="{fill}"/>')

            full_label = f"{symbol} · {size:,} B"
            full_size = fitted_font_size(full_label, item_width, item_height)
            if full_size >= 12.0:
                label, font_size = full_label, full_size
            else:
                label = symbol
                font_size = fitted_font_size(label, item_width, item_height)
            if font_size > 0:
                padding = min(4.0, item_width * 0.04)
                baseline = iy + item_height / 2 + font_size * 0.34
                svg.append(f'<text x="{ix + padding:.2f}" y="{baseline:.2f}" '
                           f'class="{label_class}" font-size="{font_size:.2f}" '
                           f'fill="{foreground}">{html.escape(label)}</text>')
            svg.append('</g>')
        svg.append('</g>')

    if SHOW_COLOUR_KEY:
        free_description = ("checkerboard = free space" if SHOW_CHECKERBOARD
                            else "transparent = free space")
        svg.extend([
            f'<rect x="16" y="862" width="12" height="12" fill="{color_for_region(0)}"/>',
            '<text x="34" y="872" class="subtitle">header colour = physical bank · '
            'rectangle colour = linker region · shade = symbol</text>',
            f'<rect x="720" y="862" width="12" height="12" fill="{free_fill()}" '
            'stroke="#8f9baa"/>',
            f'<text x="738" y="872" class="subtitle">{free_description}</text>',
        ])
        if SHOW_COLOURED_PERCENTAGES:
            svg.append(
                f'<text x="{canvas_width - 16}" y="891" text-anchor="end" '
                'class="subtitle">capacity text: amber 75–89.9% · red 90%+</text>'
            )
    svg.extend([
        f'<text x="16" y="{footer_y}" class="subtitle">Generated by {TOOL_NAME} '
        f'· compiler: {COMPILER_LABEL} · source: {html.escape(os.path.basename(MAP))}</text>',
        '</svg>',
    ])
    return "\n".join(svg) + "\n"

def make_ram_svg(regions, entries):
    """Render WRAM with a true-scale overview and address-preserving zoom panels."""
    canvas_width, canvas_height = 1200, 900
    map_x, map_y = 16, 62
    map_bottom = 856 if SHOW_COLOUR_KEY else 875
    map_width, map_height = canvas_width - 32, map_bottom - map_y
    overview_width, gap = 374, 8
    detail_x = map_x + overview_width + gap
    detail_width = map_width - overview_width - gap
    low_height = 536
    direct_y = map_y + low_height + gap
    direct_height = map_bottom - direct_y
    header_height = 30

    physical_entries = [
        (physical_ram_address(address), size, symbol, allocation)
        for _, address, size, symbol, allocation in entries
    ]
    total_size = sum(length for _, _, length in regions)
    total_used = sum(size for _, _, size, _, _ in entries)
    total_percent = 100 * total_used / total_size

    def snes_address(address):
        return f"${address >> 16:02X}:{address & 0xffff:04X}"

    def range_entries(origin, length):
        end = origin + length
        return [
            (address, size, symbol, allocation)
            for address, size, symbol, allocation in physical_entries
            if origin <= address < end
        ]

    def used_in_range(origin, length):
        end = origin + length
        return sum(
            min(address + size, end) - max(address, origin)
            for address, size, _, _ in physical_entries
            if address < end and address + size > origin
        )

    def segments(origin, length, allocations):
        end = origin + length
        cursor = origin
        result = []
        for address, size, symbol, allocation in sorted(allocations):
            start = max(origin, address)
            allocation_end = min(end, address + size)
            if allocation_end <= start:
                continue
            if start > cursor:
                result.append(("free", "unallocated", cursor, start - cursor))
            visible_start = max(start, cursor)
            if allocation_end > visible_start:
                result.append((allocation, symbol, visible_start,
                               allocation_end - visible_start))
                cursor = allocation_end
        if cursor < end:
            result.append(("free", "unallocated", cursor, end - cursor))
        return result

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {canvas_width} {canvas_height}" '
        'role="img" aria-labelledby="title description">',
        '<title id="title">SNES RAM MAP</title>',
        '<desc id="description">A true-scale overview shows all 128 KiB of WRAM in '
        'address order. Magnified panels show low WRAM and the default direct page. '
        'Colours identify allocation types; unallocated address ranges are transparent '
        'or optionally checkerboarded.</desc>',
        '<defs>',
        '  <pattern id="free-pattern" width="16" height="16" patternUnits="userSpaceOnUse">',
        '    <rect width="16" height="16" class="free-checker-a"/>',
        '    <path d="M0 0h8v8H0zM8 8h8v8H8z" class="free-checker-b"/>',
        '  </pattern>',
        '</defs>',
        f'<rect width="{canvas_width}" height="{canvas_height}" class="background"/>',
        '<text x="16" y="29" class="title">SNES RAM MAP</text>',
        '<text x="16" y="49" class="subtitle">true-scale 128 KiB overview · '
        'address-preserving low-WRAM and direct-page zooms</text>',
        f'<text x="{canvas_width - 16}" y="49" text-anchor="end" class="summary">'
        f'{total_size:,} physical bytes · {total_used:,} statically reserved · '
        f'{capacity_tspan(f"{total_percent:.1f}%", total_percent)}</text>',
        '<style>',
        '  :root { color-scheme: dark light; }',
        '  .background { fill: #10131a; }',
        '  .region-bg { fill: #080a0e; }',
        '  .free-checker-a { fill: #252b35; }',
        '  .free-checker-b { fill: #3a424f; }',
        '  .free-label { fill: #eef1f5; }',
        '  text { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; '
        'pointer-events: none; }',
        '  .title { fill: #f3f6fb; font: 700 20px system-ui, sans-serif; }',
        '  .summary, .subtitle { fill: #8f9baa; font-size: 11px; }',
        '  .capacity-warning, .capacity-critical { font-weight: 800; '
        'paint-order: stroke fill; stroke: #10131a; stroke-width: 1.4px; '
        'stroke-linejoin: round; }',
        '  .capacity-warning { fill: #ffd166; }',
        '  .capacity-critical { fill: #ff6b6b; }',
        '  .map-label { font-weight: 650; }',
        '  .region-border { stroke: #ffffff; stroke-opacity: 0.24; stroke-width: 1; '
        'vector-effect: non-scaling-stroke; }',
        '  .item { stroke: #10131a; stroke-width: 0.6; '
        'vector-effect: non-scaling-stroke; }',
        '  @media (prefers-color-scheme: light) {',
        '    .background { fill: #f5f5f5; }',
        '    .region-bg { fill: #ffffff; }',
        '    .free-checker-a { fill: #ffffff; }',
        '    .free-checker-b { fill: #cccccc; }',
        '    .free-label { fill: #202124; }',
        '    .title { fill: #15171a; }',
        '    .summary, .subtitle { fill: #59616d; }',
        '    .capacity-warning { fill: #9a6700; stroke: #ffffff; }',
        '    .capacity-critical { fill: #b42318; stroke: #ffffff; }',
        '    .region-border { stroke: #000000; stroke-opacity: 0.22; }',
        '    .item { stroke: #ffffff; }',
        '  }',
        '</style>',
    ]

    def draw_address_panel(x, y, width, height, origin, length, title, color):
        allocations = range_entries(origin, length)
        used = used_in_range(origin, length)
        percent = 100 * used / length
        header = f"{title} · {used:,}/{length:,} B · {percent:.1f}% reserved"
        header_prefix = f"{title} · {used:,}/{length:,} B"
        percentage_label = f"{percent:.1f}% reserved"
        content_x, content_y = x + 1.5, y + header_height
        content_width = max(0, width - 3)
        content_height = max(0, height - header_height - 1.5)

        svg.append(f'<g><title>{html.escape(header)}</title>')
        svg.append(f'<rect class="region-border region-bg" x="{x:.2f}" y="{y:.2f}" '
                   f'width="{width:.2f}" height="{height:.2f}"/>')
        svg.append(f'<rect x="{x + 1.5:.2f}" y="{y + 1.5:.2f}" '
                   f'width="{content_width:.2f}" height="{header_height - 1.5:.2f}" '
                   f'fill="{color}"/>')
        percentage_width = len(percentage_label) * 7.2 + 10
        header_size = fitted_font_size(
            header_prefix, content_width - percentage_width - 12, header_height - 5, 12
        )
        svg.append(f'<text x="{x + 7:.2f}" y="{y + header_height - 9:.2f}" '
                   f'class="map-label" font-size="{header_size:.2f}" '
                   f'fill="{text_color(color)}">{html.escape(header_prefix)}</text>')
        svg.append(f'<text x="{x + width - 7:.2f}" y="{y + header_height - 9:.2f}" '
                   f'text-anchor="end" class="map-label" font-size="12" '
                   f'fill="{text_color(color)}">'
                   f'{capacity_tspan(percentage_label, percent)}</text>')

        for allocation, symbol, address, size in segments(origin, length, allocations):
            item_y = content_y + (address - origin) * content_height / length
            item_height = size * content_height / length
            fill = free_fill() if allocation == "free" else RAM_COLORS[allocation]
            foreground = "#eef1f5" if allocation == "free" else text_color(fill)
            address_range = (
                f"{snes_address(address)}–{snes_address(address + size - 1)}"
            )
            if allocation == "free":
                tooltip = f"unallocated · {address_range} · {size:,} B"
                label_class = "map-label free-label"
                full_label = f"UNALLOCATED · {address_range} · {size:,} B"
            else:
                tooltip = (
                    f"{symbol} · {address_range} · {size:,} B · {allocation}"
                )
                label_class = "map-label"
                full_label = f"{symbol} · {size:,} B"
            svg.append(f'<g><title>{html.escape(tooltip)}</title>')
            svg.append(f'<rect class="item" x="{content_x:.2f}" y="{item_y:.2f}" '
                       f'width="{content_width:.2f}" height="{item_height:.2f}" '
                       f'fill="{fill}"/>')
            font_size = fitted_font_size(full_label, content_width, item_height, 11)
            if font_size >= 4:
                baseline = item_y + item_height / 2 + font_size * 0.34
                svg.append(f'<text x="{content_x + 4:.2f}" y="{baseline:.2f}" '
                           f'class="{label_class}" font-size="{font_size:.2f}" '
                           f'fill="{foreground}">{html.escape(full_label)}</text>')
            svg.append('</g>')
        svg.append('</g>')

    # The overview is globally truthful: both 64 KiB banks have equal area and every
    # vertical position corresponds to the same address offset in its bank.
    overview_color = "#4c6075"
    svg.append(f'<rect class="region-border region-bg" x="{map_x}" y="{map_y}" '
               f'width="{overview_width}" height="{map_height}"/>')
    svg.append(f'<rect x="{map_x + 1.5}" y="{map_y + 1.5}" '
               f'width="{overview_width - 3}" height="{header_height - 1.5}" '
               f'fill="{overview_color}"/>')
    svg.append(f'<text x="{map_x + 7}" y="{map_y + header_height - 9}" '
               f'class="map-label" font-size="12" fill="{text_color(overview_color)}">'
               'FULL 128 KiB · TRUE SCALE</text>')
    bank_gap = 3
    bank_y = map_y + header_height
    bank_height = map_height - header_height
    bank_width = (overview_width - 3 - bank_gap) / 2
    draw_address_panel(map_x + 1.5, bank_y, bank_width, bank_height,
                       0x7e0000, 0x10000, "$7E:0000–FFFF", color_for_region(0))
    draw_address_panel(map_x + 1.5 + bank_width + bank_gap, bank_y,
                       bank_width, bank_height, 0x7f0000, 0x10000,
                       "$7F:0000–FFFF", color_for_region(1))

    draw_address_panel(detail_x, map_y, detail_width, low_height,
                       0x7e0100, 0x1f00, "$7E:0100–1FFF · LOW WRAM ZOOM",
                       color_for_region(1))
    draw_address_panel(detail_x, direct_y, detail_width, direct_height,
                       0x7e0000, 0x100,
                       "$7E:0000–00FF · DEFAULT DIRECT PAGE (D=$0000) ZOOM",
                       color_for_region(0))

    if SHOW_COLOUR_KEY:
        legend = [
            ("initialized .data", "data"),
            ("zero-filled .bss", "bss"),
            (".noinit", "noinit"),
            ("hardware stack", "stack"),
            ("compiler DP", "compiler"),
            ("other allocated", "allocated"),
            ("unallocated", "free"),
        ]
        legend_x = [16, 177, 338, 459, 620, 769, 930]
        for (label, allocation), x in zip(legend, legend_x):
            fill = free_fill() if allocation == "free" else RAM_COLORS[allocation]
            stroke = ' stroke="#8f9baa"' if allocation == "free" else ""
            svg.append(f'<rect x="{x}" y="862" width="12" height="12" '
                       f'fill="{fill}"{stroke}/>')
            svg.append(f'<text x="{x + 18}" y="872" class="subtitle">'
                       f'{html.escape(label)}</text>')
        if SHOW_COLOURED_PERCENTAGES:
            svg.append(
                f'<text x="{canvas_width - 16}" y="891" text-anchor="end" '
                'class="subtitle">capacity text: amber 75–89.9% · red 90%+</text>'
            )

    svg.extend([
        f'<text x="16" y="891" class="subtitle">Generated by {TOOL_NAME} '
        f'· compiler: {COMPILER_LABEL} · source: {html.escape(os.path.basename(MAP))}</text>',
        '</svg>',
    ])
    return "\n".join(svg) + "\n"

if MAP_KIND == "rom":
    with open(SVG_OUT, "w", encoding="utf-8") as stream:
        stream.write(make_rom_svg(REGIONS, rows))
    entries = rows
    regions = REGIONS
else:
    with open(SVG_OUT, "w", encoding="utf-8") as stream:
        stream.write(make_ram_svg(RAM_REGIONS, ram_rows))
    entries = ram_rows
    regions = RAM_REGIONS

print(f"wrote {CSV_OUT}  ({len(entries)} entries)")
print(f"wrote {SVG_OUT}\n")
print(f"{'region':16} {'used':>8} {'capacity':>8} {'free':>8}")
total_used = 0
total_capacity = 0
for name, _, length in regions:
    used = sum(entry[2] for entry in entries if entry[0] == name)
    total_used += used
    total_capacity += length
    print(f"{name:16} {used:8} {length:8} {length - used:8}")
print(f"{'TOTAL':16} {total_used:8} {total_capacity:8} "
      f"{total_capacity - total_used:8}   "
      f"({100 * total_used / total_capacity:.1f}% allocated)")

print(f"\nbiggest {MAP_KIND.upper()} items:")
for entry in sorted(entries, key=lambda row: -row[2])[:15]:
    region, address, size, symbol = entry[:4]
    display_address = physical_ram_address(address) if MAP_KIND == "ram" else address
    print(f"  {size:7}  ${display_address:06X}  {region:16} {symbol}")
