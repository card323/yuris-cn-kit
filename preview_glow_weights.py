#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pick the Glow Sans weight the game should use, on real game text.

The engine renders every character into a 1 bpp DIB, so GDI cannot antialias and
the weight is the only lever left for how readable a line is.  Glow Sans ships
nine weights under the family name "Glow Sans SC Normal <Weight>"; this script
draws the same three sample lines (a translated Chinese line, its Japanese
original, and a kana/punctuation line) in every weight - plus the flattened
family ``Glow Sans SC`` that install_glow_sans.py registers (the face the pack
now ships) and the faces that were in play before - through the engine's exact
pipeline, at 1x and 3x, and prints each face's stroke-run profile (how many
stems are 1 px, 2 px, ... wide).

Offline analysis only; it changes no game file.
"""

from __future__ import annotations

import os
import sys

import preview_yuris_font as pv

ROOT = os.path.dirname(os.path.abspath(__file__))
SIZE = 27
PITCH = 27
WEIGHT = 400

# (face name handed to CreateFontA, short label)
FACES = [
    ("Glow Sans SC", "Glow Sans SC (shipped)"),
    ("Microsoft YaHei", "Microsoft YaHei"),
    ("Glow Sans SC Normal", "Glow Regular"),
    ("Glow Sans SC Normal Book", "Glow Book (500)"),
    ("Glow Sans SC Normal Medium", "Glow Medium (600)"),
    ("Glow Sans SC Normal Light", "Glow Light (300)"),
    ("SimSun", "SimSun 宋体"),
    ("ＭＳ ゴシック", "MS Gothic ゴシック"),
    ("Noto Sans SC", "Noto Sans SC"),
]

KANA = "「そんな……あんなの、ずるいよ」彼女はそう呟いた。"


def sample_lines() -> list[tuple[str, str]]:
    """(label, text) picked from the game's own bilingual line table."""
    path = os.path.join(ROOT, "workpack", "lines.tsv")
    rows = pv.load_lines(path) if os.path.exists(path) else []
    pick: tuple[str, str] | None = None
    for orig, new in rows:
        cn = pv._clean(new, "cn")
        jp = pv._clean(orig, "jp")
        if 16 <= len(cn) <= 27 and 14 <= len(jp) <= 27:
            pick = (jp, cn)
            break
    out = []
    if pick:
        out.append(("CN", pick[1]))
        out.append(("JP", pick[0]))
    else:
        out.append(("CN", "有些东西，还是不要让它们见到光比较好。"))
    out.append(("kana", KANA))
    return out


def main() -> int:
    lines = sample_lines()
    print("samples:")
    for label, text in lines:
        print(f"    {label:<5} {text}")
    print()

    head = f"{'face':<22}{'real face':<22}{'stroke runs':>18}  missing(CN/JP)"
    print(head)
    print("-" * (len(head) + 6))
    rows = []
    for face, label in FACES:
        usable = []
        for kind, text in lines:
            img, real = pv.compose_line(face, SIZE, text, pitch=PITCH, weight=WEIGHT)
            usable.append((kind, img))
        _probe, _b, real = pv.render_cell(face, SIZE, "國", width_px=SIZE * 3,
                                          weight=WEIGHT)
        runs = pv.stroke_runs(usable[0][1])
        tot = sum(runs.values()) or 1
        shares = " ".join(f"{k}px:{100 * runs.get(k, 0) // tot}%"
                          for k in sorted(runs)[:3])
        miss_cn = len(pv.missing_glyphs(face, lines[0][1]))
        miss_jp = len(pv.missing_glyphs(face, "".join(t for _k, t in lines)))
        flag = "" if real.upper() == face.upper() else "  <== substituted"
        print(f"{face:<22}{real:<22}{shares:>18}  {miss_cn}/{miss_jp}{flag}")
        for kind, img in usable:
            rows.append((f"{label} {kind}", img, "" if flag else ""))

    for zoom, tag in ((3, ""), (1, "-1x")):
        path = os.path.join(ROOT, f"glow_weight_sheet{tag}.png")
        pv.sheet(rows, path, f"lfHeight={SIZE}px  1bpp  white ink + (2,2) shadow"
                             f"  |  zoom={zoom}x", zoom=zoom)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
