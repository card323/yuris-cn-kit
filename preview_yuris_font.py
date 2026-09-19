#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render font candidates through the game's *exact* glyph pipeline.

Reverse-engineered facts this tool reproduces (oujunoshima.exe, YU-RIS):
  * Builder 0x4425D4 creates, per font slot, a 1 bpp top-down DIB
    (`CreateDIBSection`, biBitCount=1, height = -cell) plus a memory DC;
    it sets lfHeight/lfWeight(400|700)/lfWidth=0/lfCharSet=0x86 and the
    face name, then calls CreateFontIndirectA.
  * Renderer 0x442284 memsets the DIB to 0xFF (background = white index 1),
    SetBkMode(TRANSPARENT), SetTextColor(0) (ink = black index 0) and calls
    TextOutA once per character at (0,0), then scans the ink bbox.
  * Because the destination is 1 bpp, GDI cannot antialias: every glyph is a
    hard black/white mask.  The *face* is therefore the only quality lever.

The dialogue text size comes from `es.TD.SIZE.SET` for the "M" definition in
`data/script/userdefine/文字定義.txt` (PINT=27 PINT2=27), and the colours are
white ink with a black shadow offset by (2,2).  `--sizes 27` reproduces that.

How to choose a face
--------------------
This script is offline analysis only; it touches no game files.  It prints,
per candidate face:

  real      the face GDI actually selected (catches silent substitutions,
            e.g. "MingLiU" -> "SimSun")
  strike    ppem sizes of embedded bitmap strikes (EBLC/EBDT) - a strike that
            matches the text size gives perfectly even, hinted-by-design pixels
  jp/gbk    how many characters of the game corpus / of the whole GBK set the
            face itself has no glyph for (GDI font-links those, which is what
            makes strokes look uneven: two faces inside one line)

and writes a 1:1 + zoomed PNG of a real dialogue line in every face, drawn
white-on-dark with the game's (2,2) shadow.

The face can then be changed with:
  * the game's own config screen (設定 -> フォント一覧: live preview, no
    patching; it stores the choice in the global string gStr1146(113)), or
  * `python patch_yuris_charset.py --apply --fonts "SimSun,SimHei,MS Gothic"`
    which rewrites the engine's built-in face-name table.

Usage:
  python preview_yuris_font.py                       # installed faces, size 27
  python preview_yuris_font.py --sizes 20,27 --all
  python preview_yuris_font.py --lang cn --text "..."   # your own text
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import sys
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFont

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

DIB_RGB_COLORS = 0
TRANSPARENT = 1
GB2312_CHARSET = 0x86
DEFAULT_CHARSET = 1
GGI_MARK_NONEXISTING_GLYPHS = 1


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte),
                ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 2)]


class LOGFONTA(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG), ("lfItalic", ctypes.c_ubyte),
        ("lfUnderline", ctypes.c_ubyte), ("lfStrikeOut", ctypes.c_ubyte),
        ("lfCharSet", ctypes.c_ubyte), ("lfOutPrecision", ctypes.c_ubyte),
        ("lfClipPrecision", ctypes.c_ubyte), ("lfQuality", ctypes.c_ubyte),
        ("lfPitchAndFamily", ctypes.c_ubyte), ("lfFaceName", ctypes.c_char * 32),
    ]


gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO),
                                   wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                   wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateFontIndirectA.argtypes = [ctypes.POINTER(LOGFONTA)]
gdi32.CreateFontIndirectA.restype = wintypes.HFONT
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.TextOutA.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                           wintypes.LPCSTR, ctypes.c_int]
gdi32.GetTextFaceA.argtypes = [wintypes.HDC, ctypes.c_int, wintypes.LPSTR]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateFontA.argtypes = [
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPCSTR,
]
gdi32.CreateFontA.restype = wintypes.HFONT
gdi32.GetGlyphIndicesW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_ushort), wintypes.DWORD]
gdi32.GetGlyphIndicesW.restype = wintypes.DWORD
gdi32.EnumFontFamiliesExA.argtypes = [wintypes.HDC, ctypes.POINTER(LOGFONTA),
                                      ctypes.c_void_p, wintypes.LPARAM, wintypes.DWORD]

ENUMFONTPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.POINTER(LOGFONTA),
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.LPARAM)


def cell_for(height: int) -> int:
    """Mirror the engine's cell table (`0x7D6540[i] = 32 * (i // 8 + 2)`)."""
    return 32 * (height // 8 + 2)


def render_cell(face: str, height: int, text: str, weight: int = 400,
                charset: int = GB2312_CHARSET, quality: int = 0,
                width_px: int = 0) -> tuple[Image.Image, tuple | None, str]:
    """Rasterise `text` exactly like the engine's renderer.

    Returns (cell, bbox, real_face): the raw 1 bpp DIB the engine caches
    (black = ink, white = background), the ink bounding box inside it, and the
    face name GDI actually used.
    """
    cell = cell_for(height)
    width = max(cell, width_px or cell)
    stride = ((width * 1 + 31) // 32) * 4
    # rows top-down: biHeight negative, bit 1 = background (white), 0 = ink (black)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -cell
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 1
    bmi.bmiColors[0] = RGBQUAD(0, 0, 0, 0)        # index 0 = black (ink)
    bmi.bmiColors[1] = RGBQUAD(255, 255, 255, 0)  # index 1 = white (background)

    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(None, ctypes.byref(bmi), DIB_RGB_COLORS,
                                  ctypes.byref(bits), None, 0)
    if not hbmp:
        raise OSError(f"CreateDIBSection failed: {ctypes.get_last_error()}")
    hdc = gdi32.CreateCompatibleDC(None)
    gdi32.SelectObject(hdc, hbmp)
    # the engine memsets the whole cell to 0xFF before drawing: bit 1 = background
    ctypes.memset(bits, 0xFF, stride * cell)

    lf = LOGFONTA()
    lf.lfHeight = height
    lf.lfWidth = 0
    lf.lfWeight = weight
    lf.lfCharSet = charset
    lf.lfQuality = quality
    lf.lfFaceName = face.encode("mbcs")[:31]
    hfont = gdi32.CreateFontIndirectA(ctypes.byref(lf))
    if not hfont:
        raise OSError(f"CreateFontIndirectA failed for {face!r}")
    gdi32.SelectObject(hdc, hfont)

    gdi32.SetBkMode(hdc, TRANSPARENT)
    gdi32.SetTextColor(hdc, 0)
    raw = text.encode("gbk")
    gdi32.TextOutA(hdc, 0, 0, raw, len(raw))

    buf = ctypes.string_at(bits, stride * cell)
    real = ctypes.create_string_buffer(64)
    gdi32.GetTextFaceA(hdc, 64, real)

    gdi32.DeleteObject(hfont)
    gdi32.DeleteDC(hdc)
    gdi32.DeleteObject(hbmp)

    img = Image.frombytes("1", (stride * 8, cell), buf).convert("L").crop((0, 0, width, cell))
    bbox = img.point(lambda p: 255 - p).getbbox()
    return img, bbox, real.value.decode("mbcs", "replace")


def render_mask(face: str, height: int, weight: int = 400,
                charset: int = GB2312_CHARSET, quality: int = 0,
                text: str = "", width_px: int = 0) -> tuple[Image.Image, str]:
    """Ink-cropped glyph mask (what the engine keeps in its per-character cache)."""
    img, bbox, real = render_cell(face, height, text, weight, charset, quality, width_px)
    return (img.crop(bbox) if bbox else img), real


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


# ------------------------------------------------------------------ analysis
def missing_glyphs(face: str, chars: str) -> list[str]:
    """Characters this face has no glyph for - GDI font-links those from
    another face, and mixing faces inside one line is what makes strokes look
    uneven, so this is the number that matters."""
    if not chars:
        return []
    hdc = gdi32.CreateCompatibleDC(None)
    hfont = gdi32.CreateFontA(48, 0, 0, 0, 400, 0, 0, 0, DEFAULT_CHARSET,
                              0, 0, 0, 0, face.encode("mbcs"))
    if not hfont:
        gdi32.DeleteDC(hdc)
        return []
    old = gdi32.SelectObject(hdc, hfont)
    missing = []
    try:
        for i in range(0, len(chars), 1000):
            part = chars[i:i + 1000]
            idx = (ctypes.c_ushort * len(part))()
            gdi32.GetGlyphIndicesW(hdc, part, len(part), idx,
                                   GGI_MARK_NONEXISTING_GLYPHS)
            missing.extend(c for c, g in zip(part, idx) if g == 0xFFFF)
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hfont)
        gdi32.DeleteDC(hdc)
    return missing


def installed_faces() -> set[str]:
    """Upper-cased face names the system can hand out (same enumeration the
    engine's own font list uses)."""
    hdc = gdi32.CreateCompatibleDC(None)
    lf = LOGFONTA()
    lf.lfCharSet = DEFAULT_CHARSET
    names: set[str] = set()

    @ENUMFONTPROC
    def cb(lplf, _tm, _typ, _lp):
        try:
            raw = bytes(lplf.contents.lfFaceName)
            names.add(raw.split(b"\x00")[0].decode("mbcs", "replace").upper())
        except Exception:
            pass
        return 1

    gdi32.EnumFontFamiliesExA(hdc, ctypes.byref(lf), cb, 0, 0)
    gdi32.DeleteDC(hdc)
    return names


def gbk_charset() -> str:
    """Every character code page 936 defines (the whole set the patched engine
    can print)."""
    out = []
    for b1 in range(0x81, 0xFF):
        for b2 in range(0x40, 0xFF):
            try:
                out.append(bytes((b1, b2)).decode("gbk"))
            except UnicodeDecodeError:
                pass
    return "".join(out)


def stroke_runs(mask: Image.Image) -> dict[int, int]:
    """Horizontal ink run-length histogram: mean/1px share = stroke evenness."""
    if mask.mode != "L":
        mask = mask.convert("L")
    w, h = mask.size
    px = mask.load()
    hist: dict[int, int] = {}
    for y in range(h):
        run = 0
        for x in range(w + 1):
            if x < w and px[x, y] >= 128:
                run += 1
                continue
            if run:
                hist[run] = hist.get(run, 0) + 1
            run = 0
    return hist


# ------------------------------------------------------------------- drawing
def compose_line(face: str, height: int, text: str, pitch: int | None = None,
                 weight: int = 400, ink: int = 255, bg: int = 32,
                 shade: tuple | None = (0, 0, 0), shade_xy: tuple = (2, 2),
                 gap: int = 2, charset: int = GB2312_CHARSET, quality: int = 0
                 ) -> tuple[Image.Image, str]:
    """Draw a line the way the engine does: one 1 bpp cell per character,
    advanced by the text definition's fixed pitch, with the game's shadow."""
    pitch = pitch or height
    cells = []
    real = face
    for ch in text:
        cell, bbox, real = render_cell(face, height, ch, weight, charset, quality)
        cells.append((cell, bbox))
    boxes = [b for _c, b in cells if b]
    if not boxes:
        return Image.new("RGB", (8, 8), (bg, bg, bg)), real
    top = min(b[1] for b in boxes)
    bottom = max(b[3] for b in boxes)
    sx, sy = shade_xy if shade else (0, 0)
    w = pitch * len(text) + (sx if shade else 0) + 2 * gap
    h = (bottom - top) + (sy if shade else 0) + 2 * gap
    img = Image.new("RGB", (max(w, 8), max(h, 8)), (bg, bg, bg))
    layers = [(shade, sx, sy), (ink, 0, 0)] if shade else [(ink, 0, 0)]
    for col, ox, oy in layers:
        if col is None:
            continue
        rgb = (col, col, col) if isinstance(col, int) else col
        for i, (cell, bbox) in enumerate(cells):
            if bbox is None:
                continue
            mask = cell.point(lambda p: 255 - p).crop((0, top, cell.width, bottom))
            img.paste(Image.new("RGB", mask.size, rgb),
                      (gap + i * pitch + ox, gap + oy), mask)
    return img, real


def sheet(rows: list, out_path: str, title: str, zoom: int = 3,
          note_w: int = 240, pad: int = 10) -> str:
    """rows: [(label, line_image, note)] -> one PNG, zoomed with NEAREST so the
    pixels stay exactly the ones GDI produced."""
    f_label = _font("C:/Windows/Fonts/consola.ttf", 14)
    f_note = _font("C:/Windows/Fonts/msyh.ttc", 14)
    f_title = _font("C:/Windows/Fonts/msyh.ttc", 16)
    scaled = [(lab, im.resize((im.width * zoom, im.height * zoom), Image.NEAREST), note)
              for lab, im, note in rows]
    body_w = max((im.width for _l, im, _n in scaled), default=200)
    head = 36
    canvas = Image.new("RGB", (note_w + body_w + 2 * pad,
                               head + sum(im.height + pad for _l, im, _n in scaled) + pad),
                       (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    d.text((pad, 8), title, fill=(0, 0, 0), font=f_title)
    y = head
    for label, im, note in scaled:
        d.text((pad, y + im.height // 2 - 18), label, fill=(0, 0, 0), font=f_label)
        if note:
            d.text((pad, y + im.height // 2 + 2), note, fill=(110, 110, 110), font=f_note)
        canvas.paste(im, (note_w + pad, y))
        y += im.height + pad
    canvas.save(out_path)
    return out_path


# --------------------------------------------------------------------- input
RUBY_RE = re.compile(r"≪([^≫／/]*)[／/][^≫]*≫")
ROOT = os.path.dirname(os.path.abspath(__file__))

# (name handed to CreateFontA, Chinese note, how the system reports the face)
# GDI registers Japanese faces under their full-width katakana names, so the
# ASCII spelling only resolves through the mapper - we have to check both.
CANDIDATES = [
    ("MS Gothic", "ＭＳ ゴシック（原版 exe 默认）", "ＭＳ ゴシック"),
    ("MS UI Gothic", "ＭＳ ＵＩゴシック（日文 UI 用，稍窄）", "MS UI Gothic"),
    ("Microsoft YaHei", "微软雅黑（上一版补丁的默认值）", "Microsoft YaHei"),
    ("SimSun", "宋体（老牌点阵字体，笔锋重）", "SimSun"),
    ("NSimSun", "新宋体", "NSimSun"),
    ("SimHei", "黑体（笔画粗细均匀）", "SimHei"),
    ("DengXian", "等线（微软现代无衬线）", "DengXian"),
    ("KaiTi", "楷体（手写感）", "KaiTi"),
    ("FangSong", "仿宋", "FangSong"),
    ("Microsoft JhengHei", "微软正黑（繁体）", "Microsoft JhengHei"),
    ("MS PGothic", "ＭＳ Ｐゴシック（比例字体）", "ＭＳ Ｐゴシック"),
    ("MS Mincho", "ＭＳ 明朝（日文明朝/宋体风格）", "ＭＳ 明朝"),
    ("MS PMincho", "ＭＳ Ｐ明朝", "ＭＳ Ｐ明朝"),
    ("Meiryo", "メイリオ（日文无衬线）", "メイリオ"),
    ("BIZ UD Gothic", "BIZ UD ゴシック（日文易读设计）", "BIZ UDゴシック"),
    ("Yu Gothic", "游ゴシック（Win10 日文，需改字符集）", "游ゴシック"),
    ("Malgun Gothic", "韩文黑体（中文覆盖不够）", "Malgun Gothic"),
    ("MingLiU", "细明体（繁体，Win10 需另装）", "細明體"),
    ("Noto Sans SC", "思源黑体 Noto（当前 exe 默认值，GBK 全覆盖）", "Noto Sans SC"),
    ("Source Han Sans SC", "思源黑体（需另装）", "Source Han Sans SC"),
    ("Sarasa Gothic SC", "更纱黑体（中日互通，需另装）", "Sarasa Gothic SC"),
    ("Sarasa Mono SC", "更纱等宽（需另装）", "Sarasa Mono SC"),
    ("LXGW WenKai", "霞鹜文楷（需另装）", "LXGW WenKai"),
]

SAMPLES = {
    "jp": "桜の花びらが舞い散る、静かな午後のことだった。",
    "cn": "樱花飞舞，静谧的午后时光。",
}


def _clean(text: str, lang: str) -> str:
    text = RUBY_RE.sub(r"\1", text)
    keep = []
    for ch in text:
        if ch in "\r\n\t":
            continue
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            continue
        keep.append(ch)
    return "".join(keep)


def load_lines(path: str) -> list[tuple[str, str]]:
    """(original, translated) pairs from a work-package TSV, ruby stripped."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        try:
            i_o, i_n = head.index("orig_text"), head.index("new_text")
        except ValueError:
            return rows
        for ln in fh:
            f = ln.rstrip("\n").split("\t")
            if len(f) <= max(i_o, i_n):
                continue
            rows.append((f[i_o], f[i_n]))
    return rows


def pick_sample(rows: list, lang: str, width: int) -> str:
    """Two real dialogue lines that roughly fill the message window."""
    want = [width, int(width * 0.8)]
    picked = []
    for orig, new in rows:
        src = new if (lang == "cn" and new.strip()) else orig
        txt = _clean(src, lang)
        if not txt or txt in picked:
            continue
        if abs(len(txt) - want[len(picked)]) <= 4:
            picked.append(txt)
        if len(picked) == len(want):
            return "\n".join(picked)
    return SAMPLES[lang] if len(picked) < 2 else "\n".join(picked)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Preview and vet font faces for the patched YU-RIS "
                    "renderer (see module docstring).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="font_preview.png")
    ap.add_argument("--sizes", default="27", help="lfHeight values, default 27 "
                                                  "(the dialogue's TD size)")
    ap.add_argument("--pitch", type=int, default=None,
                    help="character pitch in px (default: same as the size)")
    ap.add_argument("--faces", default=None, help="comma separated face names")
    ap.add_argument("--all", action="store_true", help="include faces that are not installed")
    ap.add_argument("--text", default=None, help="explicit sample text (use \\n for line breaks)")
    ap.add_argument("--lang", choices=("jp", "cn"), default="jp")
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--weight", type=int, default=400,
                    help="lfWeight: 400 normal, 700 = the engine's es.TD.BOLD.SET")
    ap.add_argument("--corpus", default=None,
                    help="extra text file whose characters must be covered")
    ap.add_argument("--no-coverage", action="store_true",
                    help="skip the (slower) glyph coverage measurement")
    args = ap.parse_args(argv)

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    have = installed_faces()
    if args.faces:
        # keep the CANDIDATES note / system face name when the caller spells a
        # known face with its ASCII name (the system may report the CJK one)
        by_key = {}
        for name, note, sysname in CANDIDATES:
            by_key[name.upper()] = (name, note, sysname)
            by_key[sysname.upper()] = (name, note, sysname)
        faces = []
        for s in args.faces.split(","):
            s = s.strip()
            if s:
                faces.append(by_key.get(s.upper(), (s, "", s)))
    else:
        faces = [c for c in CANDIDATES
                 if args.all or c[0].upper() in have or c[2].upper() in have]

    rows = load_lines(os.path.join(ROOT, "workpack", "lines.tsv"))
    if args.text:
        sample = args.text.replace("\\n", "\n")
    else:
        sample = pick_sample(rows, args.lang, width=27)
    sample = "\n".join(_clean(ln, args.lang) for ln in sample.split("\n"))
    print(f"sample text : {sample!r}")

    # --- corpus ---------------------------------------------------------------
    corpus = ""
    if not args.no_coverage:
        src = [os.path.join(ROOT, "workpack", "lines.tsv"),
               os.path.join(ROOT, "yuris_text_out", "all_text.txt")]
        if args.corpus:
            src.append(args.corpus)
        chars: set[str] = set()
        for path in src:
            if not os.path.exists(path):
                continue
            if path.endswith(".tsv"):
                for orig, new in load_lines(path):
                    chars |= set(_clean(orig, args.lang)) | set(_clean(new, args.lang))
            else:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    chars |= set(_clean(fh.read(), args.lang))
        # the translated text must be renderable *and* the whole GBK set is the
        # long-term target, so measure both
        corpus_jp = "".join(sorted(c for c in chars if ord(c) > 0x7F))
        corpus_gbk = gbk_charset()
        print(f"corpus      : {len(corpus_jp)} distinct non-ASCII chars in the game text, "
              f"{len(corpus_gbk)} chars in GBK")
    else:
        corpus_jp = corpus_gbk = ""

    # --- measure --------------------------------------------------------------
    head = (f"{'face':<20}{'real face':<20}{'stroke runs':>16}"
            f"{'game text':>10}{'GBK':>9}")
    print()
    print(head)
    print("-" * (len(head) + 12))
    rendered = []
    for face, note, sysname in faces:
        _probe, _b, real = render_cell(face, sizes[0], "國", width_px=sizes[0] * 3,
                                       weight=args.weight)
        line, real = compose_line(face, sizes[0], "國語漢字", pitch=args.pitch,
                                  weight=args.weight)
        runs = stroke_runs(line)
        tot = sum(runs.values()) or 1
        shares = " ".join(f"{k}px:{100 * runs.get(k, 0) // tot}%"
                          for k in sorted(runs)[:3])
        miss_game = miss_gbk = "-"
        if corpus_jp:
            miss_game = f"{len(missing_glyphs(sysname, corpus_jp))}"
            miss_gbk = f"{len(missing_glyphs(sysname, corpus_gbk))}"
        sub = "" if real.upper() in (face.upper(), sysname.upper()) else " <== 被替换"
        if sub:
            note = (note + " | 系统没有这个字体，实际用了 " + real).strip(" |")
        print(f"{face:<20}{real:<20}{shares:>16}{miss_game:>10}{miss_gbk:>9}{sub}")
        rendered.append((face, note, real))

    # --- sheets ---------------------------------------------------------------
    for size in sizes:
        rows_out = []
        for face, note, real in rendered:
            img, real = compose_line(face, size, sample, pitch=args.pitch,
                                     weight=args.weight)
            label = face if real.upper() == face.upper() else f"{face} -> {real}"
            rows_out.append((label, img, note))
        stem, ext = os.path.splitext(args.out)
        title = (f"lfHeight={size}px  pitch={args.pitch or size}px  weight={args.weight}  "
                 f"1bpp mask, white ink + (2,2) black shadow  |  {sample}")
        for zoom, tag in ((args.zoom, ""), (1, "-1x")):
            path = f"{stem}{tag}{ext}"
            sheet(rows_out, path, f"{title}  |  zoom={zoom}x", zoom=zoom)
            print(f"wrote {path}")
    print("\nThe exe's name table only supplies the *default* face (menus, config, "
          "message windows); the dialogue and choice boxes use the face the scripts "
          "pass to FONT[NAME=...], which the config screen's font list (設定 → "
          "フォント一覧) overrides live without any patching.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

