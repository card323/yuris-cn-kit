#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Give the game a Glow Sans family name that fits in its 13-byte font literal.

The engine's scripts hand a face name straight to ``CreateFontA``, and the
literal they use - ``ＭＳ ゴシック`` - is exactly 13 bytes in a packed string
pool, so a replacement name can never be longer than that.  The installed Glow
Sans fonts are registered under family names like ``Glow Sans SC Normal Medium``
(19-24 bytes) and only carry ``Glow Sans SC`` as their *typographic* family
(name ID 16), which GDI ignores - which is why requesting ``Glow Sans SC`` makes
GDI silently substitute SimSun.

This script re-writes the name table (and the weight/selection bits, so GDI's
font mapper really hands out this file for ``lfWeight`` 400 and 700) of two Glow
Sans weights and installs them *per user* as:

    Glow Sans SC (Regular slot)  <- GlowSansSC-Normal-<weight>.otf
    Glow Sans SC Bold            <- GlowSansSC-Normal-<bold weight>.otf

It also rewrites the vertical metrics, because the engine's script both requests
the glyph height and fixes the line pitch, and GDI scales that request into the
font's ascent+descent: at Glow Sans SC's shipped 1160/-288 the dialogue renders a
third smaller than the ＭＳ ゴシック it replaces.  ``--line-metrics`` controls it.

Nothing is deleted: the renamed copies are written to
``%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts`` next to the originals and
registered under ``HKCU``, and ``--uninstall`` removes exactly those two files
and their registry values.

Usage:
  python install_glow_sans.py                     # Medium becomes "Glow Sans SC"
  python install_glow_sans.py --weight Book
  python install_glow_sans.py --weight Book --line-metrics keep   # compare
  python install_glow_sans.py --uninstall
  python install_glow_sans.py --verify            # is the family resolvable now?

The rest of the switch, in order (details in glossary/STYLE_GUIDE.md section 8):

1. build with ``--face "Glow Sans SC"`` - the default of
   ``transcode_yuris_scripts.py --face``, which ``build_cn_pack.py`` forwards;
   it does not depend on this script having run, so run this one first.
2. ``python patch_yuris_charset.py --apply --fonts "Glow Sans SC,Microsoft YaHei,SimHei"``
   for the face the *exe* uses where a script names none.
3. delete ``save\\config.sd`` (back it up) if the game already ran - a font
   picked in 設定 → フォント一覧 is stored there and overrides both.

A machine without the family is not a broken machine: the exe's face table has a
fallback chain (step 2 above), and the dialogue face in the scripts has none, so
GDI silently substitutes (SimSun) - wrong look, same behaviour.  Redistribution,
including the modified copies this script writes, is allowed by the font's SIL
Open Font License (no Reserved Font Name is declared).  See
glossary/STYLE_GUIDE.md section 8.7.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys

from ctypes import wintypes

from fontTools.ttLib import TTFont

FAMILY_DEFAULT = "Glow Sans SC"
#: vertical metrics that give Glow Sans SC a one-em line cell, like ＭＳ ゴシック.
#: The engine asks GDI for ``lfHeight = PINT2`` (the script's glyph height) but
#: keeps the *line pitch* in the script, so how big the ink comes out is decided
#: by the font's own ascent+descent: Glow Sans SC ships hhea/win 1160/-288, i.e.
#: a 1.448 em cell, which draws a 27-px request at 16 px instead of 23 px - the
#: glyphs looked small and every gap (letter and line) looked wide.  Its OS/2
#: typographic line is 880/-120 (1 em), the same convention ＭＳ ゴシック uses.
LINE_METRICS_DEFAULT = "typo"
#: suffix used by the installed Glow Sans files (see the Windows font folder)
WEIGHTS = {
    "thin": "Thin",
    "extralight": "ExtraLight",
    "light": "Light",
    "regular": "Regular",
    "book": "Book",
    "medium": "Medium",
    "bold": "Bold",
    "extrabold": "ExtraBold",
    "heavy": "Heavy",
}
FONT_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts")
REG_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(ROOT, "build", "glow-fonts")

#: the two slots the game asks for: lfWeight 400 (dialogue) and 700 (bold text)
SLOTS: tuple[tuple[str, int, bool], ...] = (
    ("GlowSansSC-CN-Regular.otf", 400, False),
    ("GlowSansSC-CN-Bold.otf", 700, True),
)

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

HWND_BROADCAST = 0xFFFF
WM_FONTCHANGE = 0x001D
SMTO_ABORTIFHUNG = 0x0002


# --------------------------------------------------------------------- install
def source_file(weight: str, font_dir: str) -> str:
    """The installed Glow Sans file that carries *weight*."""
    name = f"GlowSansSC-Normal-{weight}.otf"
    for d in (font_dir, os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")):
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    raise SystemExit(f"{name} not found in {font_dir} - install Glow Sans SC "
                     f"first (https://github.com/welai/glow-sans)")


def resolve_line_metrics(spec: str, tt: TTFont) -> tuple[int, int] | None:
    """Turn a ``--line-metrics`` value into ``(ascent, descent)`` or ``None``.

    ``typo`` means "the line the font designer declared" (``OS/2.sTypoAscender``
    and ``sTypoDescender``, which is 880/-120 for the whole Glow Sans family),
    ``keep`` leaves the file's own metrics alone and ``ASC/DESC`` sets them
    directly.  Only the ascent/descent pair changes: their *sum* is the cell GDI
    scales ``lfHeight`` into, so a smaller sum means larger glyphs.
    """
    spec = spec.strip().lower()
    if spec in ("", "keep", "none", "off"):
        return None
    if spec == "typo":
        os2 = tt["OS/2"]
        asc, desc = os2.sTypoAscender, -os2.sTypoDescender
    else:
        text = spec.replace("-", " ")
        if "/" in spec:
            text = spec.replace("/", " ")
        parts = text.split()
        if len(parts) != 2:
            raise SystemExit(f"--line-metrics {spec!r}: expected 'typo', 'keep' "
                             f"or 'ASCENT/DESCENT' (descent positive)")
        try:
            asc, desc = int(parts[0]), int(parts[1])
        except ValueError:
            raise SystemExit(f"--line-metrics {spec!r}: not two integers")
    if asc <= 0 or desc <= 0:
        raise SystemExit(f"--line-metrics {spec!r}: ascent {asc} and descent "
                         f"{desc} must both be positive")
    return asc, desc


def rename_font(src: str, dst: str, family: str, style: str, weight: int,
                bold: bool, line_metrics: str = LINE_METRICS_DEFAULT,
                ps_name: str | None = None) -> str:
    """Write *src* to *dst* under the identity (family, style, weight).

    *ps_name* overrides the PostScript name, which doubles as GDI's identity for
    the file: two loaded fonts that share one are served interchangeably, so a
    probe build needs a name of its own.
    """
    ps_name = ps_name or f"GlowSansSC-CN-{style}"
    full = family if style == "Regular" else f"{family} {style}"
    values = {
        1: family,            # legacy family - what GDI's mapper matches against
        2: style,
        3: f"1.000;WELA;{ps_name}",
        4: full,
        6: ps_name,
        16: family,           # typographic family
        17: style,
        21: family,           # WWS family
        22: style,
    }
    tt = TTFont(src)
    name = tt["name"]
    records = sorted({(r.nameID, r.platformID, r.platEncID, r.langID)
                      for r in name.names})
    # every language and platform gets the ASCII name: GDI reads the record that
    # matches the system locale, so leaving the CJK ones alone would be invisible
    # right up to the moment a Chinese Windows picks that record instead.
    for nid, pid, eid, lid in records:
        if nid in values:
            name.setName(values[nid], nid, pid, eid, lid)
    for nid in (1, 2, 4, 6):
        if not any(r[0] == nid for r in records):
            name.setName(values[nid], nid, 3, 1, 0x409)

    os2 = tt["OS/2"]
    os2.usWeightClass = weight
    if bold:
        os2.fsSelection = (os2.fsSelection | 0x20) & ~0x40       # BOLD, not REGULAR
    else:
        os2.fsSelection = (os2.fsSelection & ~0x20) | 0x40
    head = tt["head"]
    head.macStyle = (head.macStyle | 1) if bold else (head.macStyle & ~1)

    line = resolve_line_metrics(line_metrics, tt)
    if line is not None:
        asc, desc = line
        hhea = tt["hhea"]
        before = (hhea.ascender, hhea.descender, os2.usWinAscent, os2.usWinDescent)
        # hhea drives FreeType/GDI's scaled metrics, the OS/2 Windows pair the
        # cell CreateFontIndirect scales lfHeight into; both must agree or the
        # glyph can be drawn outside its line box.
        hhea.ascender, hhea.descender = asc, -desc
        os2.usWinAscent, os2.usWinDescent = asc, desc
        # never shrink the declared bounding box - some rasterisers clamp to it
        head.yMax = max(head.yMax, asc)
        head.yMin = min(head.yMin, -desc)
        print(f"    line metrics {before[0]}/{before[1]} hhea "
              f"{before[2]}/{before[3]} win -> {asc}/{-desc} "
              f"(cell {asc + desc} units, {asc + desc}/{tt['head'].unitsPerEm} em)")

    if "CFF " in tt:                    # keep the PostScript identity consistent
        cff = tt["CFF "].cff
        cff.fontNames[0] = ps_name
        top = cff.topDictIndex[0]
        for attr, val in (("FullName", full), ("FamilyName", family),
                          ("Weight", style)):
            try:
                setattr(top, attr, val)
            except Exception:
                pass

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tt.save(dst)
    tt.close()
    return ps_name


def retire(path: str) -> None:
    """Take a previously installed file out of the way, even while it is in use.

    Windows refuses to delete a font file a process has loaded but happily
    renames it, so a stale copy becomes ``.otf.replaced`` instead of blocking the
    new one.
    """
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
        return
    except OSError:
        pass
    alt = path + ".replaced"
    try:
        if os.path.exists(alt):
            os.remove(alt)
        os.replace(path, alt)
        print(f"    note: {os.path.basename(path)} was in use, renamed to "
              f"{os.path.basename(alt)}")
    except OSError as e:
        raise SystemExit(f"cannot replace {path}: {e}")


def register(path: str, full_name: str, install: bool = True) -> None:
    """Add/remove one font file in the current session and in HKCU."""
    import winreg

    if install:
        added = gdi32.AddFontResourceW(ctypes.c_wchar_p(path))
        if not added:
            print(f"    warning: AddFontResourceW({os.path.basename(path)}) "
                  f"reported no font (err {ctypes.get_last_error()})")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
            winreg.SetValueEx(key, f"{full_name} (TrueType)", 0, winreg.REG_SZ, path)
    else:
        gdi32.RemoveFontResourceW(ctypes.c_wchar_p(path))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
            try:
                winreg.DeleteValue(key, f"{full_name} (TrueType)")
            except FileNotFoundError:
                pass


def broadcast_font_change() -> None:
    """Tell every top-level window (Explorer, editors, ...) the font list moved."""
    res = wintypes.DWORD()
    user32.SendMessageTimeoutW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0,
                               SMTO_ABORTIFHUNG, 2000, ctypes.byref(res))


def verify(family: str, same_weight: bool = False) -> int:
    """Prove GDI hands out this family at both weights, from a clean process.

    ``same_weight`` marks an install that deliberately put the same Glow weight
    in both slots (the engine's font builder asks for 400 or 700 depending on a
    script flag, so the thin face has to sit in both - STYLE_GUIDE section 8.4).
    Only then are two identical renders the pass condition rather than the
    failure condition.
    """
    import preview_yuris_font as pv

    ok = True
    masks = {}
    for weight in (400, 700):
        img, _bbox, real = pv.render_cell(family, 27, "國", weight=weight,
                                          charset=pv.GB2312_CHARSET, width_px=81)
        masks[weight] = img
        same = real.upper() == family.upper()
        ok &= same
        print(f"    lfWeight={weight}: real face {real!r}"
              f"{'' if same else '   <== SUBSTITUTED'}")

    # the two slots normally have to be two different files, or "bold" is a no-op
    same_render = masks[400].tobytes() == masks[700].tobytes()
    if same_weight:
        if not same_render:
            print("    lfWeight 400 and 700 render differently although --weight "
                  "and --bold-weight name the same Glow weight")
            ok = False
        else:
            print("    lfWeight 400 and 700 render identically on purpose: "
                  "--weight == --bold-weight (STYLE_GUIDE 8.4)")
    elif same_render:
        print("    lfWeight 400 and 700 render identically - the bold slot did "
              "not install (add --same-weight if that is deliberate: --weight == "
              "--bold-weight, STYLE_GUIDE 8.4)")
        ok = False

    kana = "あいうえおアイウエオヴ々ー「」、。！？〜"
    probe = kana + "国語漢字鬱齧『新律綱領』"
    missing = pv.missing_glyphs(family, probe)
    print(f"    glyphs missing for CN+JP probe ({len(probe)} chars): "
          f"{''.join(missing) if missing else 'none'}")
    ok &= not missing

    corpus = os.path.join(ROOT, "workpack", "lines.tsv")
    if os.path.exists(corpus):
        chars = set()
        for orig, new in pv.load_lines(corpus):
            chars |= set(pv._clean(orig, "jp")) | set(pv._clean(new, "cn"))
        chars = "".join(sorted(c for c in chars if ord(c) > 0x7F))
        miss = pv.missing_glyphs(family, chars)
        print(f"    glyphs missing for the whole game corpus ({len(chars)} chars): "
              f"{len(miss)}{''.join(miss[:20])}")
        ok &= not miss
    return 0 if ok else 1


# ------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python install_glow_sans.py --weight Medium')
    ap.add_argument("--weight", default="medium",
                    help="Glow Sans weight for the regular slot: "
                         + ", ".join(sorted(set(WEIGHTS))) + " (default: medium)")
    ap.add_argument("--bold-weight", default="bold",
                    help="Glow Sans weight for the bold slot (default: bold)")
    ap.add_argument("--family", default=FAMILY_DEFAULT,
                    help=f"family name to register (default: {FAMILY_DEFAULT!r}; "
                         "must be at most 12 bytes for the 13-byte script literal)")
    ap.add_argument("--font-dir", default=FONT_DIR,
                    help="folder holding the installed Glow Sans files")
    ap.add_argument("--line-metrics", default=LINE_METRICS_DEFAULT,
                    metavar="typo|keep|ASC/DESC",
                    help="vertical metrics for the installed copy.  GDI scales "
                         "the engine's lfHeight into the font's ascent+descent, "
                         "and the script's line pitch is fixed, so Glow Sans SC's "
                         "shipped 1160/-288 (1.448 em) draws the dialogue about a "
                         "third too small with wide letter/line gaps.  'typo' "
                         "(default) copies its own 880/-120 one-em line into hhea "
                         "and the Windows metrics; 'keep' leaves them alone; "
                         "ASC/DESC sets them by hand")
    ap.add_argument("--uninstall", action="store_true",
                    help="remove the two renamed fonts again")
    ap.add_argument("--verify", action="store_true",
                    help="only check whether --family resolves at both weights")
    ap.add_argument("--same-weight", action="store_true",
                    help="internal: the install put the *same* Glow weight in both "
                         "slots on purpose, so --verify has to expect the two "
                         "weights to render identically instead of failing")
    ap.add_argument("--dry-run", action="store_true",
                    help="build the renamed files but do not install them")
    args = ap.parse_args(argv)

    if len(args.family.encode("ascii", "ignore")) > 12:
        raise SystemExit(f"family {args.family!r} is longer than 12 ASCII bytes; "
                         f"the game's font literal only has 13")

    if args.verify:
        print(f"verifying {args.family!r}")
        return verify(args.family, same_weight=args.same_weight)

    weight = WEIGHTS[args.weight.lower()]
    bold_weight = WEIGHTS[args.bold_weight.lower()]
    installed = [os.path.join(FONT_DIR, n) for n, _w, _b in SLOTS]

    if args.uninstall:
        for path, (name, _w, bold) in zip(installed, SLOTS):
            full = f"{args.family} Bold" if bold else args.family
            register(path, full, install=False)
            retire(path)
            print(f"removed {name}")
            for junk in (path + ".replaced",):
                if os.path.exists(junk):
                    try:
                        os.remove(junk)
                    except OSError:
                        pass
        broadcast_font_change()
        print("uninstalled; the game will fall back to its own default face")
        return 0

    srcs = [source_file(weight, args.font_dir), source_file(bold_weight, args.font_dir)]
    print(f"regular slot: {weight}  <- {os.path.basename(srcs[0])}")
    print(f"bold slot   : {bold_weight}  <- {os.path.basename(srcs[1])}")

    for (name, _w, bold), src in zip(SLOTS, srcs):
        full = f"{args.family} Bold" if bold else args.family
        dst = os.path.join(BUILD_DIR, name)
        ps = rename_font(src, dst, args.family, "Bold" if bold else "Regular",
                         _w, bold, line_metrics=args.line_metrics)
        print(f"    renamed -> {dst}  (PostScript {ps}, full name {full!r})")
        if args.dry_run:
            continue
        target = os.path.join(FONT_DIR, name)
        register(target, full, install=False)     # drop a previous registration
        retire(target)
        shutil.copyfile(dst, target)
        register(target, full, install=True)
        print(f"    installed -> {target}")
    if args.dry_run:
        return 0

    broadcast_font_change()
    print("verifying in a fresh process ...")
    rc = subprocess.call([sys.executable, os.path.abspath(__file__), "--verify",
                          "--family", args.family]
                         + (["--same-weight"] if weight == bold_weight else []),
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if rc:
        print("verification FAILED - the game would still fall back to another face")
        return rc
    print("ok: the game's 400/700 requests resolve to this family.  Start the game; "
          "if the dialogue does not change, see glossary/STYLE_GUIDE.md section 8 "
          "(save\\config.sd overrides it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
