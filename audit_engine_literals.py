"""Audit non-ASCII string literals inside the game's engine scripts.

The engine is a pure ANSI byte-level renderer (see patch_yuris_charset.py), so any
string the engine *compares* against text coming out of a script file must match
byte for byte.  Several of those strings (ruby delimiters and friends) live in the
engine's own scripts (``data\\script\\eris\\*``, ``data\\script\\userdefine\\*``),
which live in ``yst00000..yst00181.ybn`` and are **not** part of our translated
pack -- so they still hold CP932 bytes while our text holds GBK bytes.

This tool lists every short non-ASCII literal found in those engine scripts and
flags the ones whose CP932 bytes differ from their GBK bytes, i.e. the ones that
can silently stop matching once the text is converted to GBK.

Usage:
    python audit_engine_literals.py --indir D:\\ysbin [--max-chars 4] [--pack DIR]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import extract_yuris_text as ex

KEY = 0x801DD23F
ENGINE_MAX_IDX = 181  # yst00000..yst00181 = eris/puserdefine/puserdesign/userdefine


def gbk_bytes(s: str) -> bytes | None:
    try:
        return s.encode('gbk')
    except UnicodeEncodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--indir', default='D:\\ysbin', help='unpacked game script directory')
    ap.add_argument('--pack', default=None, help='optional pack dir: also report which literals the pack overrides')
    ap.add_argument('--max-chars', type=int, default=4, help='only report literals up to this many characters')
    args = ap.parse_args()

    indir = Path(args.indir)
    if not indir.is_dir():
        print(f'error: {indir} is not a directory', file=sys.stderr)
        return 2

    lib, _dc = ex.load_yurislib(Path(__file__).resolve().parent / 'yuris_decompiler')
    kcc = lib.YSCM(lib.Rdr((indir / 'ysc.ybn').read_bytes(), enc='cp932')).kcc
    index = {s.idx: s.path for s in lib.YSTL(lib.Rdr((indir / 'yst_list.ybn').read_bytes(), enc='cp932')).scrs}

    hits: dict[str, set[str]] = defaultdict(set)
    scanned = 0
    for f in sorted(indir.glob('yst0*.ybn')):
        stem = f.stem
        if not stem[3:].isdigit():
            continue
        idx = int(stem[3:])
        if idx > ENGINE_MAX_IDX:
            continue
        try:
            ystb = lib.YSTB(open(f, 'rb'), kcc, KEY)
        except Exception as exc:  # pragma: no cover - corrupt input
            print(f'warn: {f.name}: {type(exc).__name__}: {exc}', file=sys.stderr)
            continue
        scanned += 1
        owner = index.get(idx, f.name)
        for cmd in ystb.cmds:
            for arg in cmd.args:
                if not isinstance(arg.dat, list):
                    continue
                for ins in arg.dat:
                    s = getattr(ins, 'arg', None)
                    if getattr(ins, 'op', None) != 'str' or not isinstance(s, str):
                        continue
                    lit = s[1:-1]  # stored with surrounding double quotes
                    if not lit or len(lit) > args.max_chars or lit.isascii():
                        continue
                    hits[lit].add(owner)

    print(f'scanned {scanned} engine scripts (<={ENGINE_MAX_IDX}) in {indir}')
    print(f'{len(hits)} distinct short non-ASCII literals\n')
    print('%-6s %-10s %-22s %-22s %s' % ('lit', 'gbk?', 'cp932 bytes', 'gbk bytes', 'used by'))
    risky = []
    for lit, owners in sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        cp = lit.encode('cp932', 'replace')
        gb = gbk_bytes(lit)
        flag = 'ok'
        if gb is None:
            flag = 'NO'
        elif gb != cp:
            flag = 'DIFF'
        row = '%-6s %-10s %-22s %-22s %s' % (
            lit, flag, cp.hex(' '), gb.hex(' ') if gb else '-',
            ', '.join(sorted(o.replace('data\\script\\', '') for o in owners))[:90])
        print(row)
        if flag != 'ok':
            risky.append((lit, flag, cp, gb, sorted(owners)))

    if risky:
        print('\n!! engine literals whose bytes change under GBK (comparisons against text will break):')
        for lit, flag, cp, gb, owners in risky:
            print('   %r  %-4s cp932=%s gbk=%s  owners=%s' % (lit, flag, cp.hex(' '), gb.hex(' ') if gb else '-', owners))

    if args.pack:
        pack = Path(args.pack)
        names = {p.name.lower() for p in pack.rglob('yst*.ybn')}
        print(f'\npack {pack}: {len(names)} script entries')
        overridden = [i for i in sorted(index) if f'yst{i:05d}.ybn' in names]
        print('   indices shipped by the pack: %d' % len(overridden))
        print('   engine indices (<=%d) shipped by the pack: %s' % (
            ENGINE_MAX_IDX, ', '.join(str(i) for i in overridden if i <= ENGINE_MAX_IDX) or '(none)'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
