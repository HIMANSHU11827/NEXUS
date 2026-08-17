"""Render an Ink ANSI frame and a side-by-side design-QA contact sheet."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ANSI = re.compile(r"\x1b\[([0-9;]*)m")
DEFAULT_BG = (24, 27, 33)
DEFAULT_FG = (224, 224, 224)
BASIC = {
    30: (0, 0, 0), 31: (239, 68, 68), 32: (34, 197, 94), 33: (245, 158, 11),
    34: (59, 130, 246), 35: (167, 139, 250), 36: (34, 211, 238), 37: (224, 224, 224),
    90: (127, 135, 148), 91: (248, 113, 113), 92: (74, 222, 128), 93: (251, 191, 36),
    94: (96, 165, 250), 95: (196, 181, 253), 96: (103, 232, 249), 97: (255, 255, 255),
}


def sgr(codes: list[int], fg: tuple[int, int, int], bg: tuple[int, int, int]):
    if not codes:
        return DEFAULT_FG, DEFAULT_BG
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0:
            fg, bg = DEFAULT_FG, DEFAULT_BG
        elif code == 39:
            fg = DEFAULT_FG
        elif code == 49:
            bg = DEFAULT_BG
        elif code in BASIC:
            fg = BASIC[code]
        elif 40 <= code <= 47:
            bg = BASIC.get(code - 10, DEFAULT_BG)
        elif 100 <= code <= 107:
            bg = BASIC.get(code - 10, DEFAULT_BG)
        elif code in (38, 48) and index + 4 < len(codes) and codes[index + 1] == 2:
            color = tuple(codes[index + offset] for offset in (2, 3, 4))
            if code == 38:
                fg = color
            else:
                bg = color
            index += 4
        index += 1
    return fg, bg


def parse_line(line: str):
    spans = []
    fg, bg = DEFAULT_FG, DEFAULT_BG
    cursor = 0
    for match in ANSI.finditer(line):
        if match.start() > cursor:
            spans.append((line[cursor:match.start()], fg, bg))
        codes = [int(value) for value in match.group(1).split(';') if value] if match.group(1) else []
        fg, bg = sgr(codes, fg, bg)
        cursor = match.end()
    if cursor < len(line):
        spans.append((line[cursor:], fg, bg))
    return spans


def render_frame(source: Path, output: Path):
    text = source.read_text(encoding='utf-8', errors='replace').replace('\r', '')
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", lambda match: match.group(0) if match.group(0).endswith('m') else '', text)
    lines = text.splitlines()
    font_path = Path(r"C:\Windows\Fonts\CascadiaMono.ttf")
    font = ImageFont.truetype(str(font_path), 18)
    cell_width = 11
    cell_height = 23
    columns = max(1, max((sum(len(span[0]) for span in parse_line(line)) for line in lines), default=1))
    rows = max(1, len(lines))
    image = Image.new('RGB', (columns * cell_width + 20, rows * cell_height + 20), DEFAULT_BG)
    draw = ImageDraw.Draw(image)
    for row, line in enumerate(lines):
        column = 0
        for value, fg, bg in parse_line(line):
            for char in value:
                x = 10 + column * cell_width
                y = 8 + row * cell_height
                if bg != DEFAULT_BG:
                    draw.rectangle((x, y, x + cell_width, y + cell_height), fill=bg)
                draw.text((x, y), char, font=font, fill=fg)
                column += 1
    image.save(output)
    return image


def comparison(reference_path: Path, implementation: Image.Image, output: Path):
    reference = Image.open(reference_path).convert('RGB')
    # The selected mock includes Windows Terminal chrome. Compare the app-owned
    # terminal content only, matching the Ink capture's surface.
    if reference.height > 100 and reference.width / reference.height > 1.5:
        reference = reference.crop((0, 49, reference.width, reference.height))
    target_height = max(reference.height, implementation.height)
    if reference.height != target_height:
        reference = reference.resize((round(reference.width * target_height / reference.height), target_height))
    if implementation.height != target_height:
        implementation = implementation.resize((round(implementation.width * target_height / implementation.height), target_height))
    gutter = 32
    label_height = 44
    sheet = Image.new('RGB', (reference.width + implementation.width + gutter, target_height + label_height), (10, 12, 16))
    sheet.paste(reference, (0, label_height))
    sheet.paste(implementation, (reference.width + gutter, label_height))
    draw = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype(r"C:\Windows\Fonts\CascadiaMono.ttf", 20)
    draw.text((12, 10), 'REFERENCE', font=label_font, fill=(77, 181, 255))
    draw.text((reference.width + gutter + 12, 10), 'IMPLEMENTATION', font=label_font, fill=(77, 181, 255))
    sheet.save(output)


if __name__ == '__main__':
    if len(sys.argv) != 5:
        raise SystemExit('usage: render-preview.py FRAME.ansi IMPLEMENTATION.png REFERENCE.png COMPARISON.png')
    frame_path, implementation_path, reference_path, comparison_path = map(Path, sys.argv[1:])
    rendered = render_frame(frame_path, implementation_path)
    comparison(reference_path, rendered, comparison_path)
