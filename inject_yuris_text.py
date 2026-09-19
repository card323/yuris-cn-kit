#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inject translated text back into YU-RIS (E-Ris) game scripts.

The scripts are ``ystNNNNN.ybn`` (YSTB) binaries: a 32 byte header followed by
four XOR obfuscated blocks - commands, argument records, expression data and
line numbers.  Everything the player reads lives in ``WORD`` commands and is
stored as a bare byte string inside the shared expression block.

That expression block is a *tight tiling*: every argument record that owns
expression data points at a private byte range, and the ranges cover the block
exactly - no gap, no overlap, no unreferenced byte.  So the rewrite is simple
and provably lossless:

  1. walk the command stream and collect the records that own expression data,
  2. copy their slices into a fresh block in offset order, writing the new
     offset/size back into each record,
  3. patch ``expr_size`` in the header, re-XOR the four blocks, concatenate.

Two kinds of argument record do *not* own data and must be handled specially.
``IF``/``ELSE`` with three operands and ``LOOP`` keep one or two follow up
records whose ``off`` is still a byte offset into the expression block - it
names the expression the branch lands on - while their ``siz`` holds the target
command index (or 0 for an arm with no target).  Across the shipping scripts all
13,058 of those offsets are either another record's ``off`` or exactly
``expr_size``, so they are relocated alongside the data they point at.
``RETURNCODE`` finishes with a single placeholder record instead: its ``off`` is
always zero and its ``siz`` is the return code itself, so a rebuild never writes
to it.

The command block, the line number block and the target command index inside
every branch arm are never touched, so line numbers, labels and control flow
stay byte identical.  Only ``expr_size`` and the relocated offsets change, which
is exactly what makes a shorter *or* longer translation safe.

Modes (pick one)::

    # 1. write a translation template holding every line of the game
    python inject_yuris_text.py --indir D:\\ysbin --list translation.tsv

    # 2. prove the rewriter is byte exact (rebuild everything, expect 0 diffs)
    python inject_yuris_text.py --indir D:\\ysbin --identity-check

    # 3. apply a filled in template into a separate folder
    python inject_yuris_text.py --indir D:\\ysbin --outdir D:\\ysbin_cn \\
        --apply translation.tsv --encoding gbk

The source folder is only ever read - patched scripts are written to
``--outdir`` as an overlay holding just the scripts you changed.

Needs ``extract_yuris_text.py`` and the ``yuris_decompiler`` checkout next to
this file (pass ``--repo`` to point elsewhere).
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

try:
    import extract_yuris_text as ex
except ImportError:  # pragma: no cover
    print('error: inject_yuris_text.py must live next to extract_yuris_text.py '
          '(it reuses its yurislib loading and YSTB key handling)',
          file=sys.stderr)
    raise SystemExit(1)

YSTB_MAGIC = 0x42545359        # 'YSTB'
HEAD_FMT = '<8I'               # magic, version, ncmd, lcmd, larg, lexp, llno, pad
ARG_FMT = '<HBBII'             # kw_id, type, assignment, expr_size, expr_offset
ARG_SIZE = 12
EXPR_SIZE_OFF = 20             # offset of ``lexp`` inside the YSTB header
TEMPLATE_HEADER = ('script_idx\tscript_file\tcmd_index\tline_no\tscript_path\t'
                   'encoding\torig_text\tnew_text')
# ``orig_text``/``new_text`` come last so a stray tab inside a line of dialogue
# can not shift the other columns.
TEMPLATE_COLS = TEMPLATE_HEADER.split('\t')

SCRIPT_NAME_RE = re.compile(r'^yst(\d+)\.ybn$', re.I)


def error(msg: str) -> None:
    print(f'error: {msg}', file=sys.stderr)


def warn(msg: str) -> None:
    print(f'warning: {msg}', file=sys.stderr)


# --------------------------------------------------------------------------- #
# YSTB parsing / rewriting
# --------------------------------------------------------------------------- #

def read_blocks(raw: bytes, ff, key: int) -> tuple[int, int, list[bytearray]]:
    """Split *raw* into ``(version, ncmd, [cmds, args, expr, lnos])``, decrypted."""
    magic, ver, ncmd, lcmd, larg, lexp, llno, pad = struct.unpack_from(HEAD_FMT, raw, 0)
    if magic != YSTB_MAGIC:
        raise ValueError(f'not a YSTB script (magic {magic:08X})')
    if not (ncmd * 4 == lcmd == llno) or larg % ARG_SIZE or pad:
        raise ValueError(f'broken YSTB header (ncmd={ncmd} lcmd={lcmd} '
                         f'larg={larg} llno={llno} pad={pad})')
    off, blocks = 32, []
    for size in (lcmd, larg, lexp, llno):
        if off + size > len(raw):
            raise ValueError('a YSTB block runs past the end of the file')
        blocks.append(bytearray(raw[off:off + size]))
        off += size
    if off != len(raw):
        raise ValueError(f'{len(raw) - off} trailing byte(s) after the last block')
    for block in blocks:
        ff.xor_trans(block, key)
    return ver, ncmd, blocks


def walk_layout(cmd: bytearray, ncmd: int, kcc, nrecords: int
                ) -> tuple[list[int], dict[int, int], set[int]]:
    """Locate every argument record and classify it.

    Mirrors ``Cmd._initArgs``: ``RETURNCODE`` writes a single record without
    data, ``IF``/``ELSE`` with three operands and ``LOOP`` keep a branch target
    in the records after the first one, everything else owns its data.  Getting
    this dispatch wrong silently corrupts branch tables, so the walk asserts
    that it consumed exactly the number of records the header declares.

    Returns ``(owners, words, dummies)``: the record indices that own expression
    data, the ``WORD`` records mapped to their command index, and the
    ``RETURNCODE`` placeholder records.  A placeholder is neither: its ``off``
    is always zero and its ``siz`` is the return code itself, so both fields are
    payload and must survive a rebuild untouched.
    """
    owners: list[int] = []
    words: dict[int, int] = {}
    dummies: set[int] = set()
    ai = 0
    for i in range(ncmd):
        code, narg = cmd[4 * i], cmd[4 * i + 1]
        if code == kcc.RETURNCODE:
            dummies.add(ai)
            ai += 1
        elif code in (kcc.IF, kcc.ELSE) and narg == 3:
            owners.append(ai)
            ai += 3
        elif code == kcc.LOOP:
            owners.append(ai)
            ai += 2
        else:
            for k in range(narg):
                owners.append(ai + k)
                if code == kcc.WORD and narg == 1:
                    words[ai + k] = i
            ai += narg
    if ai != nrecords:
        raise ValueError(f'argument walk desynced ({ai} of {nrecords} records)')
    return owners, words, dummies


def walk_args(cmd: bytearray, ncmd: int, kcc, nrecords: int
              ) -> tuple[list[int], dict[int, int]]:
    """``walk_layout`` without the placeholder records."""
    owners, words, _dummies = walk_layout(cmd, ncmd, kcc, nrecords)
    return owners, words


def rebuild(raw: bytes, ff, key: int, kcc, edits: dict[int, bytes] | None = None
            ) -> tuple[bytes, int]:
    """Return ``(new_bytes, n_edits_applied)`` for one script.

    ``edits`` maps an argument record index (as reported by :func:`walk_args`)
    to its replacement bytes; records not mentioned keep their data verbatim.
    """
    _ver, ncmd, (cmd, arg, expr, lnos) = read_blocks(raw, ff, key)
    nrecords = len(arg) // ARG_SIZE
    owners, _words, dummies = walk_layout(cmd, ncmd, kcc, nrecords)

    edits = edits or {}
    order = sorted(owners,
                   key=lambda j: struct.unpack_from(ARG_FMT, arg, ARG_SIZE * j)[4])
    merged = bytearray()
    applied = 0
    moved: dict[int, int] = {}
    for j in order:
        kid, typ, aop, siz, off = struct.unpack_from(ARG_FMT, arg, ARG_SIZE * j)
        if off + siz > len(expr):
            raise ValueError(f'argument record {j} points outside the '
                             f'expression block ({off}+{siz} > {len(expr)})')
        data = bytes(expr[off:off + siz])
        if j in edits:
            data = edits[j]
            siz = len(data)
            applied += 1
        moved.setdefault(off, len(merged))
        struct.pack_into(ARG_FMT, arg, ARG_SIZE * j, kid, typ, aop, siz, len(merged))
        merged += data

    # Relocate the branch arms.  Their ``off`` is an expression offset that has
    # to follow the data it names; their ``siz`` is the target command index (or
    # 0 when the arm has no target) and stays untouched.  Every such offset is a
    # record boundary or the old block end, so the two cases below cover all of
    # them.  ``RETURNCODE`` placeholders are payload, not pointers, and are the
    # only non-owner records left exactly as they were.
    owner_set = set(owners)
    for j in range(nrecords):
        if j in owner_set or j in dummies:
            continue
        kid, typ, aop, siz, off = struct.unpack_from(ARG_FMT, arg, ARG_SIZE * j)
        if off in moved:
            new_off = moved[off]
        elif off == len(expr):
            new_off = len(merged)
        else:
            raise ValueError(f'branch arm {j} points at expression offset {off}, '
                             f'which is neither a record boundary nor the end of '
                             f'the block ({len(expr)})')
        if new_off != off:
            struct.pack_into(ARG_FMT, arg, ARG_SIZE * j, kid, typ, aop, siz, new_off)

    head = bytearray(raw[:32])
    struct.pack_into('<I', head, EXPR_SIZE_OFF, len(merged))
    for block in (cmd, arg, merged, lnos):
        ff.xor_trans(block, key)
    return bytes(head + cmd + arg + merged + lnos), applied


def word_records(raw: bytes, ff, key: int, kcc, enc: str
                 ) -> list[tuple[int, int, int, str]]:
    """Return ``[(cmd_index, arg_record, line_no, text), ...]`` in script order."""
    _ver, ncmd, (cmd, arg, expr, lnos) = read_blocks(raw, ff, key)
    _owners, words = walk_args(cmd, ncmd, kcc, len(arg) // ARG_SIZE)
    out = []
    for j, i in sorted(words.items(), key=lambda kv: kv[1]):
        kid, typ, aop, siz, off = struct.unpack_from(ARG_FMT, arg, ARG_SIZE * j)
        if kid or typ or aop:
            raise ValueError(f'WORD argument record {j} is not a plain string')
        text = bytes(expr[off:off + siz]).decode(enc)
        out.append((i, j, struct.unpack_from('<I', lnos, 4 * i)[0], text))
    return out


def word_bytes(raw: bytes, ff, key: int, kcc) -> dict[int, bytes]:
    """Return ``{cmd_index: raw string bytes}`` - the encoding free check."""
    _ver, ncmd, (cmd, arg, expr, lnos) = read_blocks(raw, ff, key)
    _owners, words = walk_args(cmd, ncmd, kcc, len(arg) // ARG_SIZE)
    out = {}
    for j, i in words.items():
        _kid, _typ, _aop, siz, off = struct.unpack_from(ARG_FMT, arg, ARG_SIZE * j)
        out[i] = bytes(expr[off:off + siz])
    return out


# --------------------------------------------------------------------------- #
# game loading
# --------------------------------------------------------------------------- #

def load_game(args):
    indir = Path(args.indir).expanduser()
    if not indir.is_dir():
        ex.die(f'input folder not found: {indir}')
    if not (indir / 'ysc.ybn').is_file():
        ex.die(f'{indir / "ysc.ybn"} not found - pass --indir <ysbin folder>')
    repo = (Path(args.repo).expanduser() if args.repo
            else Path(__file__).resolve().parent / 'yuris_decompiler')
    ff, _dc = ex.load_yurislib(repo)
    with open(indir / 'ysc.ybn', 'rb') as fp:
        yscm = ff.YSCM(ff.Rdr(fp.read(), enc=args.i_encoding))
    files = ex.ystb_files(indir)
    key = ex.resolve_key(ff, files, yscm.kcc, len(yscm.cmds), args.key, args.verbose)
    paths: dict[int, str] = {}
    try:
        with open(indir / 'yst_list.ybn', 'rb') as fp:
            for scr in ff.YSTL(ff.Rdr(fp.read(), enc=args.i_encoding)).scrs:
                paths[scr.idx] = scr.path
    except Exception as e:  # only used for the report, never fatal
        warn(f'could not read yst_list.ybn ({type(e).__name__}), '
             f'script paths will be blank')
    return ff, yscm.kcc, key, indir, files, paths


def script_index(name: str) -> str:
    m = SCRIPT_NAME_RE.match(name)
    return str(int(m.group(1))) if m else ''


def clean(text: str) -> str:
    """Make *text* safe for one TSV cell."""
    return text.replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')


# --------------------------------------------------------------------------- #
# template I/O
# --------------------------------------------------------------------------- #

def read_template(path: Path) -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        header = f.readline().rstrip('\r\n').split('\t')
        if not header or header[0] != TEMPLATE_COLS[0]:
            raise ValueError(f'{path} is not a template - expected the header '
                             f'{" / ".join(TEMPLATE_COLS)}')
        missing = [c for c in ('script_file', 'cmd_index') if c not in header]
        if missing:
            raise ValueError(f'{path} has no {", ".join(missing)} column')
        for lineno, line in enumerate(f, 2):
            line = line.rstrip('\r\n')
            if not line.strip():
                continue
            cols = line.split('\t')
            if len(cols) > len(header):
                # a tab inside the last cell - glue the tail back together
                cols = cols[:len(header) - 1] + ['\t'.join(cols[len(header) - 1:])]
            cols += [''] * (len(header) - len(cols))
            rows.append((lineno, dict(zip(header, cols))))
    return rows


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #

def mode_list(ff, kcc, key, indir, files, paths, args) -> int:
    out = Path(args.list).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    nrows = nscripts = nbad = 0
    with open(out, 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(TEMPLATE_HEADER + '\n')
        for p in files:
            try:
                recs = word_records(p.read_bytes(), ff, key, kcc, args.i_encoding)
            except Exception as e:
                nbad += 1
                warn(f'{p.name}: {type(e).__name__}: {e}')
                continue
            if not recs:
                continue
            nscripts += 1
            idx = script_index(p.name)
            spath = paths.get(int(idx)) if idx else None
            for cmd_i, _j, lno, text in recs:
                f.write('\t'.join((idx, p.name, str(cmd_i), str(lno),
                                   clean(spath or ''), '', clean(text), '')) + '\n')
                nrows += 1
    print(f'wrote {nrows} line(s) from {nscripts} script(s) to {out}')
    if nbad:
        print(f'      {nbad} script(s) could not be parsed (see the warnings)')
    print('fill the new_text column (and optionally encoding, e.g. gbk) and '
          'feed the file back with --apply')
    return 0


def mode_identity(ff, kcc, key, indir, files, paths, args) -> int:
    same = changed = failed = nwords = 0
    for p in files:
        raw = p.read_bytes()
        try:
            nwords += len(word_records(raw, ff, key, kcc, args.i_encoding))
            new, applied = rebuild(raw, ff, key, kcc)
        except Exception as e:
            failed += 1
            print(f'  FAIL  {p.name}: {type(e).__name__}: {e}')
            continue
        if new == raw and applied == 0:
            same += 1
        else:
            changed += 1
            print(f'  DIFF  {p.name}: {len(new) - len(raw):+d} byte(s)')
    total = same + changed + failed
    print(f'identity round trip: {same}/{total} file(s) byte identical, '
          f'{changed} changed, {failed} failed; {nwords} WORD string(s) walked')
    if changed or failed:
        print('FAILED - do not inject anything until this reports 0 problems')
        return 1
    print('OK - the rewriter reproduces every script byte for byte')
    return 0


def mode_apply(ff, kcc, key, indir, files, paths, args) -> int:
    tpl = Path(args.apply).expanduser()
    if not tpl.is_file():
        ex.die(f'template not found: {tpl}')
    rows = read_template(tpl)
    outdir = Path(args.outdir).expanduser()
    report_path = Path(args.report).expanduser() if args.report \
        else outdir / 'inject_report.tsv'

    known = {p.name.lower(): p for p in files}
    per_file: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for lineno, row in rows:
        per_file.setdefault(row['script_file'].strip(), []).append((lineno, row))

    report: list[tuple[str, str, str, str]] = []
    counts: dict[str, int] = {}
    written = 0
    edits_total = 0

    def note(name: str, target: str, status: str, detail: str = '') -> None:
        counts[status] = counts.get(status, 0) + 1
        report.append((name, target, status, clean(detail)))

    for name, group in per_file.items():
        src = known.get(name.lower()) or (indir / name if (indir / name).is_file() else None)
        if src is None:
            for lineno, row in group:
                note(name, row['cmd_index'], 'no-such-script',
                     f'template line {lineno}')
            continue
        raw = src.read_bytes()
        try:
            recs = word_records(raw, ff, key, kcc, args.i_encoding)
        except Exception as e:
            for lineno, row in group:
                note(src.name, row['cmd_index'], 'unparsable',
                     f'{type(e).__name__}: {e}')
            continue
        by_cmd = {i: (j, text) for i, j, _lno, text in recs}

        edits: dict[int, bytes] = {}
        wanted: dict[int, bytes] = {}
        for lineno, row in group:
            raw_cmd = row.get('cmd_index', '').strip()
            new_text = row.get('new_text', '')
            if not new_text:
                note(src.name, raw_cmd, 'empty', f'template line {lineno}')
                continue
            try:
                cmd_i = int(raw_cmd)
            except ValueError:
                note(src.name, raw_cmd, 'bad-cmd-index', f'template line {lineno}')
                continue
            hit = by_cmd.get(cmd_i)
            if hit is None:
                note(src.name, raw_cmd, 'not-a-word-command',
                     f'template line {lineno}')
                continue
            j, cur = hit
            orig = row.get('orig_text', '')
            if orig and orig != cur:
                note(src.name, raw_cmd, 'orig-text-mismatch',
                     f'expected {orig[:24]!r} found {cur[:24]!r}')
                if not args.force:
                    continue
            enc = (row.get('encoding', '').strip() or args.encoding)
            try:
                blob = new_text.encode(enc, args.errors)
            except (UnicodeEncodeError, LookupError) as e:
                bad = (e.object[e.start:e.end] if isinstance(e, UnicodeEncodeError) else '')
                note(src.name, raw_cmd, 'encode-error',
                     f'{enc}: {bad!r} not representable')
                continue
            if blob == cur.encode(args.i_encoding, 'replace'):
                note(src.name, raw_cmd, 'unchanged', 'same as the original')
                continue
            if j in edits:
                note(src.name, raw_cmd, 'duplicate-row',
                     'the same command appears twice, keeping the last one')
            edits[j] = blob
            wanted[cmd_i] = blob
            note(src.name, raw_cmd, 'applied', f'{enc}, {len(blob)} byte(s)')

        if not edits:
            continue
        if args.limit and edits_total + len(edits) > args.limit:
            edits = dict(list(edits.items())[:max(0, args.limit - edits_total)])
            if not edits:
                continue
        try:
            new, applied = rebuild(raw, ff, key, kcc, edits)
        except Exception as e:
            for cmd_i in wanted:
                note(src.name, str(cmd_i), 'rebuild-failed',
                     f'{type(e).__name__}: {e}')
            continue

        after = word_bytes(new, ff, key, kcc)
        before = word_bytes(raw, ff, key, kcc)
        broken = [i for i in before if i not in wanted and before[i] != after.get(i)]
        wrong = [i for i, blob in wanted.items() if after.get(i) != blob]
        if broken or wrong:
            for cmd_i in (broken + wrong)[:50]:
                note(src.name, str(cmd_i), 'verify-failed',
                     f'{len(broken)} untouched / {len(wrong)} edited string(s) differ')
            print(f'error: {src.name} failed verification, not writing it')
            continue

        edits_total += applied
        if not args.dry_run:
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / src.name).write_bytes(new)
            written += 1
        print(f'  {src.name}: {applied} string(s) replaced, '
              f'{len(raw)} -> {len(new)} byte(s) '
              f'({len(new) - len(raw):+d})')

    if report and not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, 'w', encoding='utf-8-sig', newline='\r\n') as f:
            f.write('script_file\tcmd_index\tstatus\tdetail\n')
            for row in report:
                f.write('\t'.join(row) + '\n')

    print()
    print(f'{"dry run - nothing written" if args.dry_run else f"wrote {written} script(s) to {outdir}"}')
    print(f'{edits_total} string(s) injected, report: '
          f'{report_path if not args.dry_run else "(skipped)"}')
    for status, n in sorted(counts.items()):
        print(f'    {n:>6}  {status}')
    if counts.get('encode-error'):
        print(f'note: {counts["encode-error"]} line(s) could not be encoded as '
              f'{args.encoding} - see the report for the offending characters')
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Inject translated text into YU-RIS (E-Ris) YSTB scripts.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python inject_yuris_text.py --indir D:\\ysbin '
               '--list translation.tsv\n'
               '         python inject_yuris_text.py --indir D:\\ysbin '
               '--outdir D:\\ysbin_cn --apply translation.tsv --encoding gbk')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='folder holding ysc.ybn and the ystNNNNN.ybn scripts')
    ap.add_argument('--outdir', default='yuris_text_in',
                    help='folder for the patched scripts (default: ./yuris_text_in)')
    ap.add_argument('--repo', default=None,
                    help='path to the yuris_decompiler checkout '
                         '(default: ./yuris_decompiler)')
    ap.add_argument('--key', default='auto',
                    help='YSTB XOR key such as 0x801DD23F, or "auto" (default)')
    ap.add_argument('--i-encoding', default='cp932',
                    help='encoding of the text inside the scripts (default: cp932)')
    ap.add_argument('--encoding', default='cp932',
                    help='encoding used for new_text (default: cp932; use gbk '
                         'for Simplified Chinese once the engine accepts it)')
    ap.add_argument('--errors', default='strict',
                    choices=('strict', 'replace', 'ignore'),
                    help='what to do with characters the encoding cannot store '
                         '(default: strict - report and skip the line)')

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--list', metavar='TSV',
                      help='write a translation template to TSV')
    mode.add_argument('--apply', metavar='TSV',
                      help='apply a filled in template')
    mode.add_argument('--identity-check', action='store_true',
                      help='rebuild every script without edits and compare')

    ap.add_argument('--report', default=None,
                    help='where to write the per row report '
                         '(default: <outdir>/inject_report.tsv)')
    ap.add_argument('--limit', type=int, default=0,
                    help='stop after N injected string(s) (for experiments)')
    ap.add_argument('--force', action='store_true',
                    help='apply a row even if orig_text does not match')
    ap.add_argument('--dry-run', action='store_true',
                    help='do everything except writing the scripts')
    ap.add_argument('-v', '--verbose', action='store_true',
                    help='print key recovery details')
    args = ap.parse_args(argv)

    ff, kcc, key, indir, files, paths = load_game(args)

    if args.list:
        return mode_list(ff, kcc, key, indir, files, paths, args)
    if args.identity_check:
        return mode_identity(ff, kcc, key, indir, files, paths, args)
    return mode_apply(ff, kcc, key, indir, files, paths, args)


if __name__ == '__main__':
    sys.exit(main())
