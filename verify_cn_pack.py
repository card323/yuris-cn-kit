#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check a pack built by ``build_cn_pack.py`` before installing it.

Every run proves eight things about the build folder:

  1. ``update1.ypf`` holds byte for byte the same scripts as the ``ysbin``
     overlay folder next to it, and no other entries;
  2. every string in the rebuilt scripts, decoded with the **real Windows code
     page 936 table** (``MultiByteToWideChar``, not Python's ``gbk`` codec),
     equals the text recorded in ``inject_input.tsv`` - so nothing is mangled,
     truncated or silently substituted on the way in;
  3. the rebuilt scripts hold exactly the same WORD commands as the originals
     they replace;
  4. the branch/layout blocks (``cmds``, ``lnos``, and the argument block size)
     are byte-identical to the originals, so no branch target or offset moved.

  5. every string an **OS dialog box** shows is still byte-identical to the
     original: a dialog is drawn by Windows with the process code page (932), not
     by the engine with the font's character set, so re-encoding one of those into
     code page 936 - the thing this pack does to every other string - is what made
     the confirm boxes come out as mojibake.  The same check also reports dialog
     text found outside the engine range, where no rule protects it.

  6. every string that **names a label** is still byte-identical to the original.
     A ``GOSUB``/``GOTO`` resolves its target against the label table
     ``ysl.ybn``, which this pack does not ship and which therefore keeps
     spelling the names in Shift-JIS, so a reference re-encoded into code page
     936 can never match its own definition - that is what aborted the chapter
     select with ``ラベル ｣ｴ｣ｵ... が 見つかりませんでした``.

  7. every dialogue line still parses as the **engine's ruby markup**.
     ``es.TX.RUBY.CHK`` (``data/script/eris/es_text.yst``) walks the text of
     every line the engine draws and ends the game with an OK-only
     ``ルビ記述エラーです。`` dialog when ``《base／reading》`` is malformed - and
     ``《``, ``》`` and ``／`` are exactly what the transcoder writes where the
     original had ``≪``, ``≫`` and ``／``.  A translated line that quotes a book
     title as ``《title》`` therefore stops the game the next time it is drawn;
     ``check_glossary.py``:``ruby_errors`` is the parser and this is the last
     chance to catch a line that slipped past it.

  8. no dialogue line holds a character the engine reads as a **control code**.
     ``es.TX.CRPREPLACE`` compares the two bytes of every full-width character
     against ``EF F0``, ``EF F2`` and ``EF F3`` and, on a match, deletes the
     character from the drawn string and puts a draw marker (``R`` log-only,
     ``P`` new page, ``C`` click wait) in its place.  Shift-JIS never assigns
     those pairs; cp936 spells 镳 矧 矬 with them, and those are ordinary words.
     The bytes are read out of the pack itself, so this catches a line that
     reached the build without passing the linter.

Usage::

    python verify_cn_pack.py build D:\\ysbin
    python verify_cn_pack.py build D:\\ysbin --verbose
"""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from pathlib import Path

try:
    import check_glossary as cg
    import inject_yuris_text as inj
    import transcode_yuris_scripts as tsc
    import ypf_tool
except ImportError:  # pragma: no cover
    print('error: verify_cn_pack.py must live next to check_glossary.py, '
          'inject_yuris_text.py, transcode_yuris_scripts.py and ypf_tool.py',
          file=sys.stderr)
    raise SystemExit(1)

_MB = ctypes.WinDLL('kernel32', use_last_error=True).MultiByteToWideChar
_MB.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p, ctypes.c_int,
                ctypes.c_wchar_p, ctypes.c_int]
_MB.restype = ctypes.c_int


def win936(data: bytes) -> str:
    """Decode *data* with the real Windows code page 936 table."""
    n = _MB(936, 0, data, len(data), None, 0)
    if n <= 0:
        raise ValueError(f'code page 936 refused {data!r}')
    buf = ctypes.create_unicode_buffer(n)
    _MB(936, 0, data, len(data), buf, n)
    return buf.value


def blocks(raw: bytes, ff, key):
    """``(version, ncmd, cmds, args, expr, lnos)``."""
    ver, ncmd, (cmd, arg, expr, lnos) = inj.read_blocks(raw, ff, key)
    return ver, ncmd, cmd, arg, expr, lnos


def word_payloads(raw: bytes, ff, key, kcc) -> list[tuple[int, int, bytes]]:
    """``[(cmd_index, line_no, payload)]`` for every WORD string of *raw*."""
    _ver, ncmd, cmd, arg, expr, lnos = blocks(raw, ff, key)
    _owners, words = inj.walk_args(cmd, ncmd, kcc, len(arg) // inj.ARG_SIZE)
    out = []
    for rec, cmd_index in sorted(words.items(), key=lambda kv: kv[1]):
        _kid, _typ, _aop, siz, off = struct.unpack_from(inj.ARG_FMT, arg,
                                                        inj.ARG_SIZE * rec)
        line_no = struct.unpack_from('<I', lnos, 4 * cmd_index)[0]
        out.append((cmd_index, line_no, bytes(expr[off:off + siz])))
    return out


def words_by_cmd(raw: bytes, ff, key, kcc) -> dict[int, bytes]:
    """``{cmd_index: raw string bytes}`` for every WORD string in *raw*."""
    return {i: payload for i, _line, payload in word_payloads(raw, ff, key, kcc)}


def literal_spans(ff, ncmd: int, cmd, arg, expr, kcc
                  ) -> list[tuple[int, int, int]]:
    """``[(record, start, end)]`` for every non-WORD literal of a script.

    ``WORD`` payloads are left out on purpose: they are dialogue lines the engine
    draws itself, so the pack legitimately translates them.  The offsets count
    from the start of the expression block.
    """
    nrecords = len(arg) // inj.ARG_SIZE
    owners, words, _dialogs = inj.walk_layout(cmd, ncmd, kcc, nrecords)
    out: list[tuple[int, int, int]] = []
    for rec in sorted(set(owners) - set(words)):
        _kid, _typ, _aop, siz, off = struct.unpack_from(inj.ARG_FMT, arg,
                                                        inj.ARG_SIZE * rec)
        payload = bytes(expr[off:off + siz])
        # ``literal_ranges`` counts from the start of the payload.
        out.extend((rec, off + s, off + e)
                   for s, e in tsc.literal_ranges(ff, payload))
    return out


def ui_spans(ff, ncmd, cmd, arg, expr, kcc, codes, ui_all: bool
             ) -> list[tuple[int, int, int]]:
    """``[(record, start, end)]`` for the literals an OS dialog box shows.

    *ui_all* marks a script whose strings all reach a dialog box, whatever command
    carries them; otherwise only the arguments of the ``DIALOG`` command and of
    calls into a dialog wrapper count.
    """
    nrecords = len(arg) // inj.ARG_SIZE
    if ui_all:
        owners, _words, _dialogs = inj.walk_layout(cmd, ncmd, kcc, nrecords)
        wanted = set(owners)
    else:
        records, _nd, _ng = tsc.dialog_records(ff, cmd, ncmd, kcc, nrecords, arg,
                                               expr, codes)
        wanted = set(records)
    return [span for span in literal_spans(ff, ncmd, cmd, arg, expr, kcc)
            if span[0] in wanted]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Verify a build_cn_pack.py build folder.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python verify_cn_pack.py build D:\\ysbin')
    ap.add_argument('build', nargs='?', default='build',
                    help='folder holding update1.ypf and ysbin\\ '
                         '(default: ./build)')
    ap.add_argument('original', nargs='?', default=r'D:\ysbin',
                    help='the unpacked original scripts (default: D:\\ysbin)')
    ap.add_argument('--repo', default=None,
                    help='path to the yuris_decompiler checkout '
                         '(default: ./yuris_decompiler)')
    ap.add_argument('--key', default='auto',
                    help='YSTB XOR key such as 0x801DD23F, or "auto" (default)')
    ap.add_argument('--i-encoding', default='cp932',
                    help='encoding of the text inside the original scripts '
                         '(default: cp932)')
    ap.add_argument('--verbose', action='store_true',
                    help='let the key detection print its score board')
    args = ap.parse_args(argv)

    build = Path(args.build).expanduser()
    overlay = build / 'ysbin'
    original = Path(args.original).expanduser()
    if not (build / 'update1.ypf').is_file():
        print(f'error: {build / "update1.ypf"} not found', file=sys.stderr)
        return 2
    if not overlay.is_dir():
        print(f'error: {overlay} not found', file=sys.stderr)
        return 2

    ns = argparse.Namespace(indir=str(original), repo=args.repo, key=args.key,
                            i_encoding=args.i_encoding, verbose=args.verbose)
    ff, kcc, key, indir, _files, paths = inj.load_game(ns)
    print(f'key 0x{key:08X}, checking {build}')

    # ---- 1. the pack must hold exactly the overlay bytes ----
    _ver, entries = ypf_tool.read_ypf(build / 'update1.ypf')
    packed = {e['name'].replace('/', '\\'): e['raw'] for e in entries}
    on_disk = {f'ysbin\\{p.name}': p.read_bytes() for p in overlay.glob('*.ybn')}
    problems: list[str] = []
    if set(packed) != set(on_disk):
        extra = sorted(set(packed) - set(on_disk))
        absent = sorted(set(on_disk) - set(packed))
        problems.append(f'pack entries differ: {len(packed)} in pack vs '
                        f'{len(on_disk)} on disk, extra {extra[:4]}, '
                        f'missing {absent[:4]}')
    else:
        differs = sorted(n for n in packed if packed[n] != on_disk[n])
        if differs:
            problems.append(f'{len(differs)} pack entrie(s) differ from the '
                            f'overlay: {differs[:4]}')
    print(f'[1] update1.ypf vs overlay: {len(packed)} entrie(s)  '
          + ('ok' if not problems else 'FAIL'))

    # ---- 2. every string must decode back to the injected text ----
    expected: dict[tuple[str, int], str] = {}
    for _i, row in inj.read_template(build / 'inject_input.tsv'):
        expected[(row['script_file'].strip().lower(),
                  int(row['cmd_index']))] = row['new_text']

    checked = unchecked = 0
    bad_text: list[str] = []
    layout: list[str] = []
    for name, raw in sorted(on_disk.items()):
        short = name.split('\\')[1]
        orig_path = original / short
        if not orig_path.is_file():
            layout.append(f'{short}: not in {original}')
            continue
        orig_raw = orig_path.read_bytes()

        ov, oncmd, ocmd, oarg, _oexpr, olnos = blocks(orig_raw, ff, key)
        nv, nncmd, ncmd, narg, _nexpr, nlnos = blocks(raw, ff, key)
        if (ov, oncmd, ocmd, olnos) != (nv, nncmd, ncmd, nlnos) \
                or len(oarg) != len(narg):
            layout.append(f'{short}: layout changed (ncmd {oncmd}->{nncmd}, '
                          f'cmd {len(ocmd)}->{len(ncmd)} B, '
                          f'arg {len(oarg)}->{len(narg)} B, '
                          f'lnos {len(olnos)}->{len(nlnos)} B)')

        got = words_by_cmd(raw, ff, key, kcc)
        if set(got) != set(words_by_cmd(orig_raw, ff, key, kcc)):
            layout.append(f'{short}: WORD command set changed')
        for cmd_index, data in got.items():
            want = expected.get((short.lower(), cmd_index))
            if want is None:
                unchecked += 1
                continue
            checked += 1
            back = win936(data)
            if back != want and len(bad_text) < 10:
                bad_text.append(f'{short}#{cmd_index}: {back!r} != {want!r}')

    print(f'[2] decoded {checked} injected string(s) back with code page 936  '
          + ('ok' if not bad_text else 'FAIL')
          + (f'  ({unchecked} string(s) had no template row)' if unchecked
             else ''))
    for line in bad_text:
        print('    ', line)

    print(f'[3] WORD command sets match the originals  '
          + ('ok' if not any('command set' in l for l in layout) else 'FAIL'))
    print(f'[4] layout blocks (cmds/lnos/arg size) unchanged  '
          + ('ok' if not any('layout changed' in l for l in layout) else 'FAIL'))
    for line in layout:
        print('    ', line)

    # ---- 5. text an OS dialog box shows must still be CP932 ----
    with open(original / 'ysc.ybn', 'rb') as fp:
        codes = {c.name: i for i, c in
                 enumerate(ff.YSCM(ff.Rdr(fp.read(), enc=args.i_encoding)).cmds)}
    ui_scripts = tuple(frag.lower() for frag in tsc.UI_SCRIPTS)
    n_ui = 0
    unpacked: list[str] = []
    bad_ui: list[str] = []
    for name, raw in sorted(on_disk.items()):
        short = name.split('\\')[1]
        orig_path = original / short
        if not orig_path.is_file():
            continue
        idx = inj.script_index(short)
        if idx is None:
            continue
        index = int(idx)
        ui_all = any(frag in paths.get(index, '').lower() for frag in ui_scripts)
        try:
            _ov, oncmd, (ocmd, oarg, oexpr, _ol) = inj.read_blocks(
                orig_path.read_bytes(), ff, key)
            _nv, nncmd, (_ncmd, narg, nexpr, _nl) = inj.read_blocks(raw, ff, key)
            spans = ui_spans(ff, oncmd, ocmd, oarg, oexpr, kcc, codes, ui_all)
        except Exception as e:
            bad_ui.append(f'{short}: {type(e).__name__}: {e}')
            continue
        if spans and index > tsc.DEFAULT_MAX_IDX:
            unpacked.append(f'{short} (index {index}): {len(spans)} dialog '
                            f'string(s) outside the engine range, where the keep '
                            f'rule does not run')
            continue
        if len(narg) != len(oarg) or len(nexpr) != len(oexpr):
            continue            # check 4 already reported this
        for rec, start, end in spans:
            want = bytes(oexpr[start:end])
            if not any(b >= 0x80 for b in want):
                continue
            n_ui += 1
            if bytes(nexpr[start:end]) != want and len(bad_ui) < 10:
                bad_ui.append(f'{short} record {rec}: the pack holds '
                              f'{bytes(nexpr[start:end])!r} where the original '
                              f'has {want!r}')

    print(f'[5] the {n_ui} string(s) an OS dialog box shows are still CP932  '
          + ('ok' if not bad_ui and not unpacked else 'FAIL'))
    for line in unpacked + bad_ui:
        print('    ', line)

    # ---- 6. a string that names a label must still be CP932 ----
    # The label table ``ysl.ybn`` is not part of this pack, so it keeps spelling
    # every name in Shift-JIS, and the engine compares a reference against it byte
    # for byte.  A reference the pack re-encoded into code page 936 can therefore
    # never match its own definition - that is what aborted the chapter select.
    #
    # Every original script is walked, not only the ones in the pack: a script the
    # pack does not carry is the original file, so what the game loads and what is
    # compared here are the same bytes either way.
    labels = tsc.collect_label_names(original, ff, args.i_encoding)
    n_lbl = 0
    bad_lbl: list[str] = []
    if not labels:
        bad_lbl.append(f'{original / "ysl.ybn"} could not be read - no label '
                       f'reference could be checked')
    n_names = sum(1 for l in labels if not l.isascii())
    for orig_path in sorted(original.glob('yst*.ybn')):
        short = orig_path.name
        if not inj.script_index(short):
            continue                    # a table, not a script
        orig_raw = orig_path.read_bytes()
        raw = on_disk.get(f'ysbin\\{short}', orig_raw)
        try:
            _ov, oncmd, (ocmd, oarg, oexpr, _ol) = inj.read_blocks(
                orig_raw, ff, key)
            _nv, nncmd, (_ncmd, narg, nexpr, _nl) = inj.read_blocks(raw, ff, key)
            spans = literal_spans(ff, oncmd, ocmd, oarg, oexpr, kcc)
        except Exception as e:
            bad_lbl.append(f'{short}: {type(e).__name__}: {e}')
            continue
        if len(narg) != len(oarg) or len(nexpr) != len(oexpr):
            continue            # check 4 already reported this
        for rec, start, end in spans:
            want = bytes(oexpr[start:end])
            # An ASCII literal is never re-encoded, and an English label name would
            # match far too much prose to be a useful signal.
            if not any(b >= 0x80 for b in want):
                continue
            if tsc.literal_text(want) not in labels:
                continue
            n_lbl += 1
            got = bytes(nexpr[start:end])
            if got != want and len(bad_lbl) < 10:
                bad_lbl.append(f'{short} record {rec}: the pack holds {got!r} '
                               f'where the original has {want!r} for the label '
                               f'{tsc.literal_text(want)!r}')

    print(f'[6] the {n_lbl} string(s) naming one of the {n_names} non-ASCII '
          f'label(s) of ysl.ybn are still CP932  '
          + ('ok' if not bad_lbl else 'FAIL'))
    for line in bad_lbl:
        print('    ', line)

    # ---- 7. every dialogue line must parse as the engine's ruby markup ----
    # The grammar and the reason it matters are in the module docstring.  The
    # parser is check_glossary.ruby_errors, so the linter the translator runs and
    # this gate agree by construction.
    bad_ruby: list[str] = []
    n_ruby = 0
    for name, raw in sorted(on_disk.items()):
        short = name.split('\\')[1]
        for cmd_index, line_no, payload in word_payloads(raw, ff, key, kcc):
            text = cg.substitute(win936(payload))
            if not any(ch in text for ch in cg.RUBY_ALL):
                continue
            n_ruby += 1
            for msg in cg.ruby_errors(text):
                if len(bad_ruby) < 10:
                    bad_ruby.append(f'{short} #{cmd_index} (line {line_no}): '
                                    f'{msg}')

    print(f'[7] the {n_ruby} dialogue line(s) holding a ruby delimiter parse  '
          + ('ok' if not bad_ruby else 'FAIL'))
    for line in bad_ruby:
        print('    ', line)

    # ---- 8. no dialogue line may hold an engine control character ----
    # The mapping and the reason it matters are in the module docstring.  The
    # bytes come out of the pack itself, decoded with the same table the engine
    # uses, so what is compared here is what the game will read.
    bad_ctrl: list[str] = []
    warn_ctrl: list[str] = []
    n_ctrl = 0
    n_reserved = 0
    for name, raw in sorted(on_disk.items()):
        short = name.split('\\')[1]
        for cmd_index, line_no, payload in word_payloads(raw, ff, key, kcc):
            for ch, pair, effect, fatal in cg.control_hits(win936(payload)):
                line = (f'{short} #{cmd_index} (line {line_no}): {ch!r} is cp936 '
                        f'{pair}, the engine reads it as a control code - {effect}')
                if fatal:
                    n_ctrl += 1
                    if len(bad_ctrl) < 10:
                        bad_ctrl.append(line)
                else:
                    n_reserved += 1
                    if len(warn_ctrl) < 10:
                        warn_ctrl.append(line)

    print(f'[8] {n_ctrl} engine control character(s) in the drawn text  '
          + ('ok' if not bad_ctrl else 'FAIL')
          + (f'  ({n_reserved} reserved pair(s) drawn as glyphs)'
             if n_reserved else ''))
    for line in bad_ctrl + warn_ctrl:
        print('    ', line)

    problems += (bad_text + layout + unpacked + bad_ui + bad_lbl + bad_ruby
                 + bad_ctrl)
    if problems:
        print(f'FAIL: {len(problems)} problem(s)')
        return 1
    print(f'PASS: {build / "update1.ypf"} is safe to install')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
