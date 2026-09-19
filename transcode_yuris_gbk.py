#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-encode every line of a YU-RIS script set from CP932 into GBK (CP936).

Why this exists
---------------
The engine is a pure ANSI renderer (one ``TextOutA`` call site) and the patched
executable asks GDI for code page **936**, so the byte stream inside a ``WORD``
string must be a valid *GBK* byte sequence.  Text that is still the original
Shift-JIS is decoded as GBK, which turns every kana and kanji into mojibake -
mapping a CP932 byte pair onto the GBK table almost never lands on the same
character.

Re-encoding the Japanese text into GBK fixes that without translating anything:
the characters stay the same, only their byte representation changes, and GBK
carries the full kana set (hiragana, katakana, the CJK ideographs the scripts
use).  This is also why the package has to be regenerated *after* the code page
patch: a CP932 script set can not be read by a CP936 engine.

Four characters are exceptions
------------------------------
``≪``, ``≫``, ``・`` and ``♪`` have no GBK mapping at all (verified against
``WideCharToMultiByte(936, WC_NO_BEST_FIT_CHARS, ...)`` - asking for a best fit
silently yields ``?``, which is worse than a substitution).  They are replaced
by the nearest GBK character:

    ``≪`` -> ``《``      ``≫`` -> ``》``
    ``・`` -> ``·``      ``♪`` -> ``。``

Both the middle dot and the two angle brackets keep the 'box drawing' look of
the original.  The substitution map lives in ``SUBSTITUTIONS`` below; every
other character in the shipping scripts encodes losslessly.

The output is an ordinary injection template (the format
``inject_yuris_text.py --list`` writes), with ``new_text`` already filled in
and ``encoding`` set to ``gbk``::

    python transcode_yuris_gbk.py --indir D:\\ysbin --out gbk_pass.tsv
    python inject_yuris_text.py --indir D:\\ysbin --outdir cn\\ysbin \\
        --apply gbk_pass.tsv --encoding gbk

Every string keeps its original *byte* length: a kana or kanji is two bytes in
CP932 and two bytes in GBK, ASCII stays one byte, and all four substitutions are
two bytes as well.  So the rebuilt scripts are the same size as the originals
and no layout, box width or offset in the game shifts - the report prints the
number of lines where this does not hold (expected: zero).
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

try:
    import inject_yuris_text as inj
except ImportError:  # pragma: no cover
    print('error: transcode_yuris_gbk.py must live next to inject_yuris_text.py',
          file=sys.stderr)
    raise SystemExit(1)

#: Unicode chars CP936 cannot store, mapped to the closest GBK character.
SUBSTITUTIONS: dict[str, str] = {
    '\u226a': '\u300a',      # ≪  -> 《
    '\u226b': '\u300b',      # ≫  -> 》
    '\u30fb': '\u00b7',      # ・  -> ·
    '\u266a': '\u3002',      # ♪  -> 。
}

CODEPAGE = 936
WC_NO_BEST_FIT_CHARS = 0x400
ENC = 'gbk'


def substitute(text: str) -> tuple[str, dict[str, int]]:
    """Apply :data:`SUBSTITUTIONS`, returning the text and a per-char count."""
    hits: dict[str, int] = {}
    out: list[str] = []
    for ch in text:
        rep = SUBSTITUTIONS.get(ch)
        if rep is None:
            out.append(ch)
        else:
            hits[ch] = hits.get(ch, 0) + 1
            out.append(rep)
    return ''.join(out), hits


def _wide_to_cp936(text: str) -> tuple[int, bytes, int]:
    """``WideCharToMultiByte`` on *text*, returning ``(n, buffer, default_used)``."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = k32.WideCharToMultiByte
    fn.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int,
                   ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
                   ctypes.POINTER(ctypes.c_int)]
    fn.restype = ctypes.c_int
    buf = ctypes.create_string_buffer(len(text) * 3 + 2)
    used = ctypes.c_int(0)
    n = fn(CODEPAGE, WC_NO_BEST_FIT_CHARS, text, len(text), buf, len(buf),
           None, ctypes.byref(used))
    return n, buf.raw, used.value


def windows_cp936_can_encode(text: str) -> bool:
    """True when the *system* CP936 table (what GDI uses) maps every char.

    ``str.encode('gbk')`` uses Python's bundled table, which is close to but not
    identical to the one in ``kernel32``; the engine talks to GDI, so the
    authoritative answer comes from ``WideCharToMultiByte``.
    """
    if not text:
        return True
    n, _buf, used = _wide_to_cp936(text)
    return n > 0 and not used


def windows_cp936_encode(text: str) -> bytes:
    """Encode *text* with the *system* CP936 table - the engine's byte table.

    Raises :class:`UnicodeEncodeError` when a character has no code page 936
    mapping: ``WC_NO_BEST_FIT_CHARS`` makes Windows report the substitution
    instead of quietly writing ``?`` (which is what the old, unpatched rendering
    would have shown anyway).  Use :func:`substitute` first, it removes the four
    characters the shipping scripts use that the table refuses.
    """
    if not text:
        return b''
    n, raw, used = _wide_to_cp936(text)
    if n <= 0 or used:
        bad = ''.join(ch for ch in text if not windows_cp936_can_encode(ch))
        raise UnicodeEncodeError('cp936', text, 0, len(text),
                                 f'not representable: {bad[:16]!r}')
    return raw[:n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Re-encode a YU-RIS script set from CP932 into GBK and '
                    'write an inject_yuris_text.py template.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python transcode_yuris_gbk.py --indir D:\\ysbin '
               '--out gbk_pass.tsv')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='folder holding ysc.ybn and the ystNNNNN.ybn scripts')
    ap.add_argument('--out', default='gbk_pass.tsv',
                    help='template to write (default: ./gbk_pass.tsv)')
    ap.add_argument('--repo', default=None,
                    help='path to the yuris_decompiler checkout '
                         '(default: ./yuris_decompiler)')
    ap.add_argument('--key', default='auto',
                    help='YSTB XOR key such as 0x801DD23F, or "auto" (default)')
    ap.add_argument('--i-encoding', default='cp932',
                    help='encoding of the text inside the scripts '
                         '(default: cp932)')
    ap.add_argument('--verbose', action='store_true',
                    help='let the key detection print its score board')
    args = ap.parse_args(argv)

    indir = Path(args.indir).expanduser()
    eargs = argparse.Namespace(indir=str(indir), repo=args.repo,
                               i_encoding=args.i_encoding, key=args.key,
                               verbose=args.verbose)
    ff, kcc, key, indir, files, paths = inj.load_game(eargs)
    print(f'key 0x{key:08X}, {len(files)} script(s) in {indir}')

    out = Path(args.out).expanduser()
    if out.parent != Path(''):
        out.parent.mkdir(parents=True, exist_ok=True)

    nrows = nscripts = nskip = nbad = 0
    n_same_len = n_shorter = n_longer = 0
    subs: dict[str, int] = {}
    refused: list[tuple[str, str, str]] = []
    encodable: dict[str, bool] = {}

    with open(out, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(inj.TEMPLATE_HEADER + '\n')
        for p in files:
            try:
                recs = inj.word_records(p.read_bytes(), ff, key, kcc,
                                        args.i_encoding)
            except Exception as e:
                nbad += 1
                print(f'warning: skipping {p.name}: {type(e).__name__}: {e}',
                      file=sys.stderr)
                continue
            if not recs:
                continue
            idx = inj.script_index(p.name)
            spath = paths.get(int(idx)) if idx else None
            for cmd_i, _j, lno, text in recs:
                new, hits = substitute(text)
                for ch, n in hits.items():
                    subs[ch] = subs.get(ch, 0) + n
                bad = next((c for c in new
                            if not encodable.setdefault(
                                c, windows_cp936_can_encode(c))), None)
                if bad is not None:
                    refused.append((p.name, str(cmd_i), bad))
                    continue
                old_b = text.encode(args.i_encoding)
                try:
                    new_b = new.encode(ENC)
                except UnicodeEncodeError as e:
                    bad = e.object[e.start:e.end]
                    refused.append((p.name, str(cmd_i), bad))
                    continue
                if len(new_b) == len(old_b):
                    n_same_len += 1
                elif len(new_b) < len(old_b):
                    n_shorter += 1
                else:
                    n_longer += 1
                if new_b == old_b:
                    nskip += 1
                f.write('\t'.join((idx, p.name, str(cmd_i), str(lno),
                                   inj.clean(spath or ''), ENC,
                                   inj.clean(text), inj.clean(new))) + '\n')
                nrows += 1
            nscripts += 1

    print(f'wrote {nrows} line(s) from {nscripts} script(s) to {out}')
    if nbad:
        print(f'      {nbad} script(s) could not be parsed')
    if subs:
        print('substitutions applied (character has no GBK mapping):')
        for ch, n in sorted(subs.items(), key=lambda kv: -kv[1]):
            print(f'    {ch} (U+{ord(ch):04X}) -> {SUBSTITUTIONS[ch]}  x{n}')
    else:
        print('substitutions applied: none')
    print(f'byte length kept: {n_same_len} line(s)'
          f'{f", {n_longer} longer" if n_longer else ""}'
          f'{f", {n_shorter} shorter" if n_shorter else ""}')
    print(f'{nskip} line(s) are pure ASCII - identical in both code pages, '
          f'the injector will report them as unchanged')
    if refused:
        print(f'FATAL: {len(refused)} line(s) can not be stored as GBK:')
        for name, cmd_i, ch in refused[:20]:
            print(f'    {name} cmd {cmd_i}: {ch!r} (U+{ord(ch[0]):04X})')
        return 1
    print('every line is representable in GBK')
    print()
    print('next:')
    print(f'    python inject_yuris_text.py --indir {args.indir} '
          f'--outdir cn\\ysbin --apply {out} --encoding gbk')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
