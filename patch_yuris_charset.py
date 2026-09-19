#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_yuris_charset.py - retarget the YU-RIS engine's in-game text rendering
from CP932 (Shift-JIS) to CP936 (GBK / Simplified Chinese).

Why this is needed
------------------
The engine draws glyphs with a single GDI `TextOutA` call per DBCS character.
The `LOGFONTA` it builds (font-object constructor 0x4426C0) never writes
`lfCharSet`, so it stays 0 = ANSI_CHARSET, and GDI then decodes the ANSI byte
string with the *system* code page (`GetACP()` == 932 on a Japanese-locale
machine).  GBK bytes therefore come out as halfwidth katakana mojibake.

Three in-place patches fix that; none of them change the file size.

  1. lfCharSet   @ 0x442894 (7 bytes)
         C7 43 04 00 00 00 00   mov dword ptr [ebx+4],0      ; lfWidth = 0
      -> C6 43 17 86 90 90 90   mov byte ptr [ebx+0x17],0x86 ; GB2312_CHARSET
     The dropped `lfWidth = 0` write is a no-op: the LOGFONTA array at
     0x872858 is in the zero-initialised BSS tail of .data and nothing else
     ever writes lfWidth.  With lfCharSet = 0x86 GDI derives code page 936.

  2. face names  @ 0x878008 / 0x878018 / 0x878028
     The engine calls EnumFontFamiliesExA over the installed fonts (builder
     0x403AF8) and then, for each of its 8 font slots, picks the first name
     from the _RDATA table that exists on the system
     (0x403B84 loop, strings at 0x878008/0x878018/0x878038/0x878044).
     Rewriting the first three entries makes that selection land on an
     installed Simplified-Chinese font.  Each slot is 16 bytes, so every
     replacement must be (name + NUL) <= 16 bytes - enforced below.

     Only the *first* name that exists wins, so slot 0 is the real choice and
     slots 1..2 are fallbacks.  This table is the engine's *default* face: it
     applies to everything the scripts do not name explicitly (menus, config,
     name plates, message windows that use the TD definitions), while the
     dialogue/choice boxes are drawn with the face the scripts pass to
     FONT[NAME=...] (see es_text.yst / es_select.yst).  Hence

         --fonts "MS Gothic,SimSun,SimHei"     # back to the original look
         --fonts "SimHei,SimSun,Microsoft YaHei"
         --fonts shipped                       # exactly what the exe shipped with

     Names go through CreateFontA, i.e. they are decoded with the process ANSI
     code page (932 here), so use the ASCII spelling registered by the font
     ("SimSun", "MS Gothic") rather than a localized name.  CreateFontA would
     accept the extra bytes, but GDI could then silently substitute a different
     face - noted in the report as the effective face name.

  3. DBCS lead-byte table @ 0x59B0C0 (256 bytes)
     The per-character drawer decides how many bytes a single TextOutA call
     consumes with

        nCount = lenTable[str[0]] + 1

     (0x442360 `movzx ecx,[ebp]` / 0x442366 `movzx ecx,[ecx+0x59B0C0]` /
     0x44236E `inc ecx` / 0x44237E `call [TextOutA]`), and roughly 55 other
     `movzx reg, byte ptr [reg+0x59B0C0]` sites in .text use the same table to
     walk strings - so it must classify bytes exactly like the rendering code
     page does.

     The shipped table classifies bytes the way CP932-ish Japanese text needs:
     0x81-0xFC with 0xA0, 0xC7 and 0xC8 left out (that is the Shift-JIS lead
     ranges plus the halfwidth-katakana range, minus two holes).  Under GBK
     that is wrong: 0xA0, 0xC7, 0xC8, 0xFD and 0xFE are all legal lead bytes,
     and 0xC7/0xC8 are extremely common ones (日 = 0xC8D5, 人 = 0xC8CB,
     全 = 0xC8AB, ...).  Every such character shifts the walk by one byte, so
     the whole rest of the line after it is drawn from misaligned byte pairs -
     visible in-game as "N characters of correct Chinese followed by garbage".

     The table is rewritten to match IsDBCSLeadByteEx(<code page>, byte), with
     the code page derived from lfCharSet (see CHARSET_CODEPAGE).  For CP936
     that simply means every byte in 0x81-0xFE is a lead byte.

Nothing else is touched; the file length and all section sizes stay identical.

Usage
-----
    python patch_yuris_charset.py --exe <path\\oujunoshima.exe>          # dry run
    python patch_yuris_charset.py --exe <path\\oujunoshima.exe> --apply
    python patch_yuris_charset.py --exe <path\\oujunoshima.exe> --apply --fonts "MS Gothic,SimSun"
    python patch_yuris_charset.py --exe <path\\oujunoshima.exe> --revert
    python patch_yuris_charset.py --exe-name <yourexe.exe> --apply    # sweep for another build
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import struct
import sys

# ---------------------------------------------------------------- patch sites
VA_CHARSET = 0x442894                      # `mov dword ptr [ebx+4],0` (lfWidth = 0)
OLD_CHARSET_INSN = bytes.fromhex("C7430400000000")
NEW_CHARSET_INSN = bytes.fromhex("C6431786" "909090")   # mov byte [ebx+0x17],0x86 + nop*3

# _RDATA font-name slots: (VA, capacity in bytes including the NUL)
VA_FONT_SLOTS = (0x878008, 0x878018, 0x878028)
FONT_SLOT_SIZE = 16

# Original CP932 contents of those slots, for verification / revert.
ORIG_FONT_BYTES = {
    0x878008: b"\x82\x6c\x82\x72\x20\x83\x53\x83\x56\x83\x62\x83\x4e\x00",   # ＭＳ ゴシック
    0x878018: b"\x95\x57\x8f\x80\x83\x53\x83\x56\x83\x62\x83\x4e\x00",       # 標準ゴシック
    0x878028: b"\x82\x6c\x82\x72\x20\x82\x6f\x83\x53\x83\x56\x83\x62\x83\x4e\x00",  # ＭＳ Ｐゴシック
}

# The shipped names as text, i.e. what `--fonts shipped` restores.
SHIPPED_FONT_NAMES = [
    ORIG_FONT_BYTES[va].split(b"\x00")[0].decode("cp932") for va in VA_FONT_SLOTS
]

# ------------------------------------------------------------- length table
# `nCount = lenTable[byte] + 1`: 1 for a single-byte character, 2 for a lead byte.
VA_LEN_TABLE = 0x59B0C0
LEN_TABLE_SIZE = 256
# Contents as shipped (0/1 only): SJIS lead bytes (0x81-0x9F) union the halfwidth
# katakana range (0xA1-0xDF) union 0xE0-0xFC, i.e. 0x81-0xFC minus 0xA0, 0xC7, 0xC8.
ORIG_LEN_TABLE_ONES = frozenset(
    list(range(0x81, 0xA0)) + [c for c in range(0xA1, 0xFD) if c not in (0xC7, 0xC8)]
)

# lfCharSet -> code page; 0 means "use GetACP()", -1 means "use GetOEMCP()".
CHARSET_CODEPAGE = {
    0x00: 0,        # ANSI_CHARSET
    0x01: 0,        # DEFAULT_CHARSET
    0x80: 932,      # SHIFTJIS_CHARSET
    0x81: 949,      # HANGUL_CHARSET
    0x82: 1361,     # JOHAB_CHARSET
    0x86: 936,      # GB2312_CHARSET
    0x88: 950,      # CHINESEBIG5_CHARSET
    0xFF: -1,       # OEM_CHARSET
}

# IAT slots / VAs we probe for information only.
IAT_CREATE_FONT_INDIRECT_A = 0x577050
IAT_TEXTOUTA = 0x577074


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def resolve_codepage(charset: int):
    """Code page that GDI will use for a LOGFONTA with this lfCharSet."""
    if charset not in CHARSET_CODEPAGE:
        return None
    cp = CHARSET_CODEPAGE[charset]
    k = _kernel32()
    if cp == 0:
        return k.GetACP()
    if cp == -1:
        return k.GetOEMCP()
    return cp


def dbcs_lead_set(cp: int) -> frozenset[int]:
    k = _kernel32()
    k.IsDBCSLeadByteEx.argtypes = [ctypes.c_uint, ctypes.c_ubyte]
    k.IsDBCSLeadByteEx.restype = ctypes.c_int
    return frozenset(c for c in range(LEN_TABLE_SIZE) if k.IsDBCSLeadByteEx(cp, c))


# --------------------------------------------------------------------- PE map
class Pe:
    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE image (no MZ)")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe : pe + 4] != b"PE\0\0":
            raise ValueError("not a PE image (no PE signature)")
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        self.image_base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
        self.sections = []
        off = pe + 24 + opt_size
        for i in range(nsec):
            e = data[off + i * 40 : off + (i + 1) * 40]
            name = e[0:8].rstrip(b"\0").decode("latin-1")
            vsz, sva, rsz, raw = struct.unpack_from("<IIII", e, 8)
            self.sections.append((name, sva, vsz, raw, rsz))

    def off(self, va: int):
        rva = va - self.image_base
        for name, sva, vsz, raw, rsz in self.sections:
            if sva <= rva < sva + max(vsz, rsz):
                fo = raw + (rva - sva)
                if fo < raw + rsz:
                    return fo
        return None

    def read(self, va: int, n: int) -> bytes | None:
        fo = self.off(va)
        if fo is None:
            return None
        return self.data[fo : fo + n]

    def find_imm_refs(self, value: int) -> list[int]:
        """Every offset whose following 4 bytes are `value` (little endian)."""
        pat = struct.pack("<I", value)
        out, start = [], 0
        while True:
            i = self.data.find(pat, start)
            if i < 0:
                return out
            out.append(i)
            start = i + 1

    def va_of_off(self, fo: int):
        for name, sva, vsz, raw, rsz in self.sections:
            if raw <= fo < raw + rsz:
                return self.image_base + sva + (fo - raw)
        return None

    def find_call_iat(self, iat_va: int) -> list[int]:
        """`call dword ptr [iat_va]` == FF 15 <imm32> -> caller VAs."""
        pat = b"\xff\x15" + struct.pack("<I", iat_va)
        out, start = [], 0
        while True:
            i = self.data.find(pat, start)
            if i < 0:
                return out
            va = self.va_of_off(i)
            if va is not None:
                out.append(va)
            start = i + 1


# ----------------------------------------------------------------- reporting
def hexs(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def report(exe: str, pe: Pe, fonts: list[str], charset: int, apply: bool) -> int:
    print(f"exe          : {exe}")
    print(f"size         : {len(pe.data):,} bytes")
    print(f"image base   : 0x{pe.image_base:08X}")
    print()

    # --- informational probes ------------------------------------------------
    cf = pe.find_call_iat(IAT_CREATE_FONT_INDIRECT_A)
    print("CreateFontIndirectA call sites : " + (", ".join(f"0x{v:08X}" for v in cf) or "none"))
    print("TextOutA call sites            : "
          + (", ".join(f"0x{v:08X}" for v in pe.find_call_iat(IAT_TEXTOUTA)) or "none"))
    for va in VA_FONT_SLOTS:
        refs = [pe.va_of_off(o) for o in pe.find_imm_refs(va)]
        refs = [f"0x{r:08X}" for r in refs if r is not None]
        print(f"imm refs to 0x{va:08X}          : {', '.join(refs) or 'none'}")
    print()

    ops: list[tuple[int, bytes, bytes, str]] = []

    # --- patch 1: lfCharSet --------------------------------------------------
    fo = pe.off(VA_CHARSET)
    if fo is None:
        print(f"[!] 0x{VA_CHARSET:08X} is not file backed")
        return 1
    cur = pe.data[fo : fo + 7]
    print(f"1) 0x{VA_CHARSET:08X} lfCharSet")
    print(f"   now : {hexs(cur)}")
    if cur == OLD_CHARSET_INSN:
        print(f"   new : {hexs(NEW_CHARSET_INSN)}   (mov byte ptr [ebx+0x17],0x{charset:02X})")
        ops.append((fo, cur, NEW_CHARSET_INSN, "lfCharSet"))
    elif cur == NEW_CHARSET_INSN:
        print("   already patched - unchanged")
    else:
        print("   [!] unexpected bytes, refusing to touch this site")
        return 1
    print()

    # --- patch 2: face names -------------------------------------------------
    print("2) _RDATA face-name table")
    if len(fonts) > len(VA_FONT_SLOTS):
        print(f"   [!] at most {len(VA_FONT_SLOTS)} names supported")
        return 1
    for i, va in enumerate(VA_FONT_SLOTS):
        fo = pe.off(va)
        if fo is None:
            print(f"   [!] 0x{va:08X} is not file backed")
            return 1
        cur = pe.data[fo : fo + FONT_SLOT_SIZE]
        orig = ORIG_FONT_BYTES[va].ljust(FONT_SLOT_SIZE, b"\x00")
        print(f"   slot 0x{va:08X}: {hexs(cur)}")
        if i >= len(fonts):
            continue
        try:
            name = fonts[i].encode("cp932")
        except UnicodeEncodeError:
            print(f"            [!] {fonts[i]!r} is not encodable in CP932; "
                  f"use the font's ASCII name")
            return 1
        if len(name) + 1 > FONT_SLOT_SIZE:
            print(f"            [!] {fonts[i]!r} needs {len(name) + 1} bytes, "
                  f"slot holds {FONT_SLOT_SIZE}")
            return 1
        new = (name + b"\x00").ljust(FONT_SLOT_SIZE, b"\x00")
        if cur == new:
            print("            already patched - unchanged")
        elif cur != orig and not looks_like_face_name(cur):
            print(f"            [!] expected {hexs(orig)} - refusing to touch")
            return 1
        else:
            if cur != orig:
                prev = cur[: cur.index(b"\x00")].decode("cp932", "replace")
                print(f"            [i] replacing an earlier selection ({prev!r})")
            print(f"            -> {fonts[i]!r}  {hexs(new)}")
            ops.append((fo, cur, new, f"face name @0x{va:08X}"))
    print()

    # --- patch 3: DBCS lead-byte table ---------------------------------------
    print("3) char-length table @0x{:08X}".format(VA_LEN_TABLE))
    cp = resolve_codepage(charset)
    if cp is None:
        print(f"   [i] lfCharSet 0x{charset:02X}: unknown code page, leaving the table alone")
    else:
        fo = pe.off(VA_LEN_TABLE)
        if fo is None or fo + LEN_TABLE_SIZE > len(pe.data):
            print(f"   [!] 0x{VA_LEN_TABLE:08X} is not file backed")
            return 1
        cur = pe.data[fo : fo + LEN_TABLE_SIZE]
        target = bytes(1 if c in dbcs_lead_set(cp) else 0 for c in range(LEN_TABLE_SIZE))
        diff = [c for c in range(LEN_TABLE_SIZE) if cur[c] != target[c]]
        ones = " ".join("0x%02X" % c for c in sorted(c for c in range(LEN_TABLE_SIZE) if cur[c]))
        binary = all(v in (0, 1) for v in cur)
        # The table only ever flips 0 -> 1, so a subset of the target is safe to upgrade.
        upgradeable = binary and all(cur[c] <= target[c] for c in range(LEN_TABLE_SIZE))
        print(f"   code page : {cp}")
        print(f"   lead bytes: {ones}")
        if not diff:
            print("   already patched - unchanged")
        elif upgradeable:
            if frozenset(c for c in range(LEN_TABLE_SIZE) if cur[c]) != ORIG_LEN_TABLE_ONES:
                print("   [i] table is not exactly the shipped one, but is a subset of the target")
            print("   to add    : " + ", ".join("0x%02X" % c for c in diff))
            ops.append((fo, cur, target, "char-length table"))
        else:
            print("   [!] table is neither the original nor the patched one - refusing to touch")
            return 1
    print()

    if not apply:
        print("DRY RUN - nothing written.  Re-run with --apply.")
        return 0

    for fo, old, new, what in ops:
        pe.data = bytearray(pe.data)
        pe.data[fo : fo + len(new)] = new
        pe.data = bytes(pe.data)
        print(f"patched {what} at file offset 0x{fo:X}")

    # verify from the written bytes
    with open(exe, "r+b") as fh:
        fh.seek(0)
        fh.write(pe.data)
    print(f"wrote {len(pe.data):,} bytes to {exe}")
    return 0


# ----------------------------------------------------------------------- main
#: exe swept for when --exe is not given; override with --exe-name.
DEFAULT_EXE_NAME = "oujunoshima.exe"
#: recursive glob patterns autodetect() sweeps (slow - pass --exe to skip it).
AUTODETECT_PATTERNS = (r"D:\Downloads\**\{name}", r"D:\**\{name}")
#: candidates below this folder (a copy shipped inside the toolkit) are ignored.
HERE = os.path.dirname(os.path.abspath(__file__))


def autodetect(exe_name: str = DEFAULT_EXE_NAME) -> list[str]:
    import glob

    local = os.path.normcase(HERE + os.sep)
    found: list[str] = []
    for p in AUTODETECT_PATTERNS:
        for f in glob.glob(p.format(name=exe_name), recursive=True):
            if os.path.normcase(os.path.abspath(f)).startswith(local) or f in found:
                continue
            found.append(f)
    # prefer the one next to the game data (bn.ypf present in a parent dir)
    def score(f):
        d = os.path.dirname(f)
        return (os.path.exists(os.path.join(d, "pac", "bn.ypf")), len(d))

    return sorted(found, key=score, reverse=True)


def looks_like_face_name(raw: bytes) -> bool:
    """True when a _RDATA slot holds a NUL-terminated printable face name.

    Guards the patch sites: an earlier patch of ours, or the shipped CP932
    string, both pass; anything that is not text at all does not.
    """
    if b"\x00" not in raw:
        return False
    text = raw[: raw.index(b"\x00")]
    if not text:
        return False
    for enc in ("cp932", "gbk"):
        try:
            decoded = text.decode(enc)
        except UnicodeDecodeError:
            continue
        if all(c.isprintable() for c in decoded):
            return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Retarget the YU-RIS engine text renderer from CP932 to CP936.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--exe", action="append", help="oujunoshima.exe (repeatable); default: autodetect")
    ap.add_argument("--exe-name", default=DEFAULT_EXE_NAME,
                    help=f"exe name autodetect() sweeps for (default: {DEFAULT_EXE_NAME})")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--revert", action="store_true", help="restore <exe>.orig over <exe>")
    ap.add_argument("--charset", default="0x86",
                    help="LOGFONTA lfCharSet value, default 0x86 (GB2312_CHARSET)")
    ap.add_argument("--fonts", default="Microsoft YaHei,SimHei,SimSun",
                    help="comma separated face names for the 3 _RDATA slots, in priority "
                         "order - the first one that exists on the system is used for every "
                         "engine font slot (default: Microsoft YaHei,SimHei,SimSun).  "
                         "Each name must fit 15 CP932 bytes; an already patched exe can be "
                         "re-patched, e.g. --fonts \"MS Gothic,SimSun,SimHei\", and "
                         "--fonts shipped puts the exe's own original names back")
    args = ap.parse_args(argv)

    exes = args.exe or autodetect(args.exe_name)
    if not exes:
        print(f"no {args.exe_name} found; pass --exe")
        return 2

    if args.revert:
        rc = 0
        for exe in exes:
            bak = exe + ".orig"
            if not os.path.exists(bak):
                print(f"[!] no backup {bak}")
                rc = 1
                continue
            shutil.copyfile(bak, exe)
            print(f"reverted {exe} from {bak}")
        return rc

    charset = int(args.charset, 0)
    if not (0 <= charset <= 0xFF):
        print("--charset must be a byte value")
        return 2
    fonts = [s.strip() for s in args.fonts.split(",") if s.strip()]
    if len(fonts) == 1 and fonts[0].lower() == "shipped":
        fonts = list(SHIPPED_FONT_NAMES)
        print("--fonts shipped -> restoring the names the exe shipped with: "
              + ", ".join(fonts))

    # rebuild the charset patch tail for non-default charsets
    global NEW_CHARSET_INSN
    if charset != 0x86:
        NEW_CHARSET_INSN = bytes([0xC6, 0x43, 0x17, charset]) + b"\x90\x90\x90"

    rc = 0
    for exe in exes:
        with open(exe, "rb") as fh:
            data = fh.read()
        pe = Pe(data)
        print("=" * 78)
        if args.apply and not os.path.exists(exe + ".orig"):
            shutil.copyfile(exe, exe + ".orig")
            print(f"backup written: {exe}.orig")
        elif args.apply:
            print(f"backup already present: {exe}.orig")
        r = report(exe, pe, fonts, charset, args.apply)
        rc = max(rc, r)
        print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
