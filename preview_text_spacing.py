#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pick the cell width, the height and the letter spacing on real game text.

The renderer advances a character by the text definition's ``PINT`` - a full
width character by the whole cell, a half width one by half of it - plus
``@gInt1144(36,19)`` pixels, and it draws the glyphs at ``PINT2``.  The two are
not the same number: the engine's font builder asks GDI for ``lfHeight=PINT2``
with ``lfWidth=0``, so a wide face keeps its natural proportions whatever
``PINT`` is and the cell only decides how far the pen moves.  A face whose ink is
wide for its advance (Glow Sans SC against ＭＳ ゴシック) therefore wants a cell
*narrower* than it is tall: that closes the gap between two full width characters
without shrinking the glyphs - while the same pixels come off a half width
advance twice as hard, which is what the Latin row is here to show.

This draws the same sample lines at every candidate value through the engine's
exact pipeline, with the engine's own per-character advance, so a value can be
judged (and the Latin line checked for overlap) before anything is written into a
script.  Only analysis; it changes no game file.
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw

import preview_yuris_font as pv

ROOT = os.path.dirname(os.path.abspath(__file__))
FACE = "Glow Sans SC"
WEIGHT = 400          # the weight install_glow_sans.py put in the regular slot

SAMPLES = [
    ("CN", "有些东西，还是不要让它们见到光比较好。"),
    ("JP", "桜の花びらが舞い散る、静かな午後のことだった。"),
]

# A line with Latin in it, the worst case for tightening: the engine gives a
# half width character half the cell, so the same pixels come off a much
# narrower advance.
LATIN = "「CG モードだ。OK？」"


def half_width(ch: str) -> bool:
    """Whether the engine advances this character by half the cell.

    ``es_text.yst`` keeps the two advances in a metrics table (``@sInt3814``):
    the full cell for the wide forms and half of it for the ones that are stored
    in one byte, which is exactly the ASCII and the half width katakana ranges.
    """
    o = ord(ch)
    return 0x20 <= o <= 0x7E or 0xFF61 <= o <= 0xFF9F or o in (0x00A5, 0x203E)


def compose(face: str, cell: int, height: int, text: str, space: int,
            weight: int = WEIGHT, bg: int = 32) -> tuple[Image.Image, str]:
    """Draw *text* the way the engine lays it out: cell *cell*, glyphs *height*."""
    cells = []
    real = face
    for ch in text:
        box, bbox, real = pv.render_cell(face, height, ch, weight)
        cells.append((box, bbox))
    boxes = [b for _c, b in cells if b]
    if not boxes:
        return Image.new("RGB", (8, 8), (bg, bg, bg)), real
    top = min(b[1] for b in boxes)
    bottom = max(b[3] for b in boxes)
    adv = [((cell // 2) if half_width(ch) else cell) + space for ch in text]
    gap = 3
    w = sum(adv) + 2
    h = (bottom - top) + 2 + 2 * gap
    img = Image.new("RGB", (max(w, 8), max(h, 8)), (bg, bg, bg))
    x = gap
    for (cell, bbox), step in zip(cells, adv):
        if bbox is not None:
            mask = cell.point(lambda p: 255 - p).crop((0, top, cell.width, bottom))
            for col, ox, oy in ((0, 2, 2), (255, 0, 0)):
                rgb = (col, col, col)
                img.paste(Image.new("RGB", mask.size, rgb),
                          (x + ox, gap + oy), mask)
        x += step
    return img, real


def gaps(face: str, cell: int, height: int, text: str, space: int,
         weight: int = WEIGHT) -> list[tuple[int, bool]]:
    """The ink gap the renderer leaves between each pair of neighbours.

    ``[(pixels, the pair is half width), ...]`` - a gap of 0 means the strokes
    touch, a negative one means they overlap.  Measured from the glyph's ink
    bounding box, the same thing GDI rasterises, not from the font's metrics.
    """
    cells = [pv.render_cell(face, height, ch, weight) for ch in text]
    adv = [((cell // 2) if half_width(ch) else cell) + space for ch in text]
    x, spans = 3, []
    for (_cell, bbox, _real), step in zip(cells, adv):
        spans.append((x + bbox[0], x + bbox[2]) if bbox else None)
        x += step
    out = []
    for i in range(1, len(text)):
        a, b = spans[i - 1], spans[i]
        if a is None or b is None:
            continue
        out.append((b[0] - a[1], half_width(text[i]) or half_width(text[i - 1])))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--face', default=FACE)
    ap.add_argument('--weight', type=int, default=WEIGHT)
    ap.add_argument('--height', type=int, default=38,
                    help='PINT2, the height the glyphs are drawn at '
                         '(default: 38, the shipped 32)')
    ap.add_argument('--cell', type=int, default=None,
                    help='PINT, the advance of a full width character '
                         '(default: --height, the square cell the game uses)')
    ap.add_argument('--spaces', default='-2,-4,-6,-8',
                    help='letter spacing values to draw, comma separated')
    ap.add_argument('--zoom', type=int, default=3)
    ap.add_argument('--out', default=None)
    args = ap.parse_args(argv)
    spaces = [int(s) for s in args.spaces.split(',') if s.strip()]
    cell = args.cell if args.cell is not None else args.height

    _, _r, real = pv.render_cell(args.face, args.height, "囗", args.weight)
    print(f'face {args.face!r} -> {real!r}, cell {cell}px, glyphs '
          f'{args.height}px, weight {args.weight}')
    if real.upper() != args.face.upper():
        print('  (GDI substituted another face - the pack would look like this)')
    head = f'{"spacing":>8}{"CN full width":>16}{"JP full width":>16}{"latin half":>14}'
    print(head)
    print('-' * len(head))
    for space in spaces:
        cells = []
        for _label, text in SAMPLES + [("latin", LATIN)]:
            g = gaps(args.face, cell, args.height, text, space, args.weight)
            full = [p for p, half in g if not half]
            half = [p for p, half in g if half]
            cells.append(f'{min(full)}..{max(full)}px' if full
                         else (f'{min(half)}..{max(half)}px' if half else '-'))
        print(f'{space:>+8}' + ''.join(f'{c:>16}' for c in cells[:2])
              + f'{cells[2]:>14}')

    rows = []
    for space in spaces:
        for label, text in SAMPLES + [("latin", LATIN)]:
            img, _real = compose(args.face, cell, args.height, text, space,
                                 args.weight)
            note = f'spacing {space:+d}px'
            if label == "latin":
                g = [p for p, half in gaps(args.face, cell, args.height, text,
                                           space, args.weight) if half]
                note += f'  half width ink gap {min(g)}..{max(g)}px' if g else ''
            rows.append((f'{label} {space:+d}', img, note))
    titles = (f'cell={cell}px height={args.height}px  '
              f'spacing={"/".join(f"{s:+d}" for s in spaces)}'
              f'  1bpp white ink + (2,2) shadow  |  zoom={args.zoom}x')
    out = args.out or os.path.join(
        ROOT, f'spacing_sheet_{cell}x{args.height}px.png')
    pv.sheet(rows, out, titles, zoom=args.zoom)
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
