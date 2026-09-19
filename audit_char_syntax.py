"""Audit every byte the engine reads as *syntax* instead of a glyph.

The engine's text layer maps a few byte sequences to drawing commands rather than
characters: ``es.TX.CRPREPLACE`` (``data/script/eris/es_text.yst``) turns the pairs
``EF F0``/``EF F2``/``EF F3`` into "log only" / "page break" / "click wait" and
**deletes** the character from the string it is about to draw.  The originals are
Shift-JIS, where those pairs are unassigned, so only *newly authored* text - our
Chinese translation, transposed to GBK - can ever hit them.

This tool re-checks the whole surface in one run:

  A  originals, WORD payloads .......... pairs the engine would delete
  B  originals, other literals ......... same, outside the drawn text
  C  overlay (our pack), WORD payloads .. the shipped translation
  D  overlay, other literals ........... engine scripts after GBK transcoding
  E  transcoding can it invent a pair . cp932 text re-encoded as gbk
  F  marker-run literals ............... authored "structure strings" (expect none)

Only A-E matter; any hit there is a real bug.  See STYLE_GUIDE.md section 4.4.

example: python audit_char_syntax.py --indir D:\\ysbin --overlay build\\ysbin
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import inject_yuris_text as inj
import verify_cn_pack as vp

PAIRS = [bytes.fromhex('ef f0'), bytes.fromhex('ef f1'),
         bytes.fromhex('ef f2'), bytes.fromhex('ef f3')]
MARKERS = re.compile(rb'^[0-9cCRPEZ]{3,}$')
NOT_SCRIPTS = {'yst.ybn'}


def _scan_literals(folder: Path, ff, key, kcc, label: str
                   ) -> tuple[Counter, Counter, list[str]]:
    """Count control pairs in every non-WORD literal of *folder*.

    Also returns the per-pair counter of pairs that GBK transcoding would
    *create* out of a cp932 literal, plus a few detail lines.
    """
    pairs: Counter = Counter()
    invented: Counter = Counter()
    detail: list[str] = []
    for path in sorted(folder.glob('*.ybn')):
        if path.name in NOT_SCRIPTS:
            continue
        raw = path.read_bytes()
        try:
            _v, ncmd, cmd, arg, expr, _lnos = vp.blocks(raw, ff, key)
            spans = vp.literal_spans(ff, ncmd, cmd, arg, expr, kcc)
        except Exception as exc:
            if label == 'original':
                detail.append(f'  skipped {path.name} ({type(exc).__name__})')
            continue
        for rec, start, end in spans:
            payload = bytes(expr[start:end])
            for pair in PAIRS:
                n = payload.count(pair)
                if n:
                    pairs[pair] += n
                    at = payload.find(pair)
                    lo = max(0, at - 12)
                    detail.append(f'  {label} {path.name} rec#{rec} {pair.hex(" ")} x{n} '
                                  f'...{payload[lo:at + 14].hex(" ")}...')
            if MARKERS.match(payload):
                detail.append(f'  {label} {path.name} rec#{rec} marker-run '
                              f'len={len(payload)} {payload[:40].decode()}')
            if label != 'original':
                continue
            try:
                text = payload.decode('cp932')
            except UnicodeDecodeError:
                continue
            try:
                gbk = text.encode('gbk')
            except UnicodeEncodeError:
                continue
            if gbk == payload:
                continue
            for pair in PAIRS:
                if pair in gbk:
                    invented[pair] += 1
                    detail.append(f'  original->gbk {path.name} rec#{rec} '
                                  f'{pair.hex(" ")} {text!r}')
    return pairs, invented, detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Check every byte the engine reads as text syntax.',
        epilog='example: python audit_char_syntax.py --indir D:\\ysbin')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='unpacked original scripts (default: D:\\ysbin)')
    ap.add_argument('--overlay', default='build/ysbin',
                    help='our GBK-transcoded scripts (default: build/ysbin)')
    ap.add_argument('--repo', default=None, help='yuris_decompiler checkout')
    ap.add_argument('--key', default='auto', help='YSTB XOR key, or "auto"')
    ap.add_argument('--i-encoding', default='cp932')
    args = ap.parse_args(argv)

    ns = argparse.Namespace(indir=args.indir, repo=args.repo, key=args.key,
                            i_encoding=args.i_encoding, verbose=False)
    ff, kcc, key, indir, files, _paths = inj.load_game(ns)
    overlay = Path(args.overlay).expanduser()
    print(f'key 0x{key:08X}; original {indir}; overlay {overlay}')

    result: dict[str, Counter] = {}
    detail: list[str] = []
    nwords = 0
    for label, folder in (('original', Path(indir)), ('overlay', overlay)):
        if not folder.is_dir():
            print(f'error: {folder} is not a folder', file=sys.stderr)
            return 2
        pairs: Counter = Counter()
        for path in sorted(folder.glob('*.ybn')):
            raw = path.read_bytes()
            try:
                words = vp.word_payloads(raw, ff, key, kcc)
            except Exception:
                continue
            for _ci, line_no, payload in words:
                nwords += 1
                for pair in PAIRS:
                    n = payload.count(pair)
                    if n:
                        pairs[pair] += n
                        detail.append(f'  {label} {path.name} line {line_no} '
                                      f'{pair.hex(" ")} x{n} ({payload!r})')
        result[f'WORD {label}'] = pairs
        lit, invented, det = _scan_literals(folder, ff, key, kcc, label)
        result[f'literal {label}'] = lit
        if label == 'original':
            result['transcode invents'] = invented
        detail.extend(det)

    bad = 0
    print(f'{nwords} WORD string(s) scanned')
    for name in ('WORD original', 'literal original', 'WORD overlay',
                 'literal overlay', 'transcode invents'):
        pairs = result[name]
        hits = sum(pairs.values())
        bad += hits
        mark = 'ok' if not hits else 'FAIL'
        extra = ''
        if hits:
            extra = '  ' + ', '.join(f'{p.hex(" ")}={pairs[p]}' for p in PAIRS)
        print(f'  [{name:>18}] {mark}{extra}')
    if detail:
        print('  detail:')
        for line in detail[:40]:
            print(line)
        if len(detail) > 40:
            print(f'  ... {len(detail) - 40} more line(s)')
    print('audit:', 'ok - no control byte pair in any drawn string' if not bad
          else f'{bad} hit(s) - reword the lines listed above (STYLE_GUIDE 4.4)')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
