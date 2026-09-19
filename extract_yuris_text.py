#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract the text of a YU-RIS (E-Ris) game from its ``ysbin`` folder.

The game scripts are ``ystNNNNN.ybn`` binaries (YSTB format) whose data blocks
are XOR-obfuscated with a game specific 32 bit key.  This tool does two stages:

  1. **decompile** - call ``y_decompile`` from the `yuris_decompiler` project to
     rewrite every script as readable pseudo source (``CMD[ARG=...]`` lines,
     ``#labels`` and bare text lines).
  2. **extract** - walk the script table (``yst_list.ybn``), parse every YSTB
     again and dump each ``WORD[]`` string (the text actually displayed in the
     game window: narration and dialogue) as plain UTF-8 text, one line per
     message, in script order.

Usage::

    python extract_yuris_text.py --indir D:\\ysbin --outdir D:\\ysbin_text

Output::

    <outdir>/decompiled/...      stage 1 result, mirrors the game's data tree
    <outdir>/text/...            one .txt per script, mirrors the data tree
    <outdir>/all_text.txt        every text line, grouped per script
    <outdir>/text_index.tsv      script_index, script_path, line_no, text

Requires the `yuris_decompiler` repository next to this script (or pass
``--repo``) plus its dependency ``murmurhash2``; everything else is stdlib.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import struct
import sys
from collections import Counter
from pathlib import Path

# Keys used by the YSTB versions documented in yuris_decompiler/yuris_note.md,
# plus the key seen in E-Ris v555 builds; ``--key auto`` tries them before
# falling back to automatic key recovery.
KNOWN_KEYS = (0x07B4024A, 0xD36FAC96, 0x801DD23F)

TEXT_CMD = 'WORD'
JP_RE = re.compile('[\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f]')


def die(msg: str) -> None:
    print(f'error: {msg}', file=sys.stderr)
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# yurislib loading
# --------------------------------------------------------------------------- #

def load_yurislib(repo: Path):
    """Import yurislib from *repo* and lift its supported version range."""
    if not (repo / 'yurislib' / '__init__.py').is_file():
        die(f'{repo} does not look like the yuris_decompiler repository '
            f'(pass its path with --repo)')
    sys.path.insert(0, str(repo))
    import yurislib.fileformat as ff
    import yurislib.decompiler as dc
    # fileformat *and* decompiler keep their own copy of the version bounds
    # (decompiler does ``from .fileformat import *``), so both must be lifted.
    ff.Vma = dc.Vma = max(ff.Vma, 1 << 16)
    return ff, dc


def detect_version(ff, indir: Path) -> int:
    """Return the version stored in the ybn headers of *indir*."""
    vers = set()
    for p in sorted(indir.glob('*.ybn')):
        head = p.read_bytes()[:8]
        if len(head) == 8:
            vers.add(struct.unpack_from('<I', head, 4)[0])
    if not vers:
        die(f'no *.ybn files found in {indir}')
    if len(vers) > 1:
        print(f'note: mixed versions {sorted(vers)}, using the highest')
    ver = max(vers)
    if ver < ff.Vmi:
        die(f'version {ver} is older than the supported {ff.Vmi}')
    return ver


# --------------------------------------------------------------------------- #
# YSTB key handling
# --------------------------------------------------------------------------- #

def ystb_files(indir: Path) -> list[Path]:
    return sorted(p for p in indir.glob('yst[0-9]*.ybn') if p.stat().st_size > 32)


def read_sections(p: Path):
    """Split a YSTB file into its raw (still XOR-obfuscated) blocks."""
    b = p.read_bytes()
    _, _ver, ncmd, lcmd, larg, lexp, llno, _pad = struct.unpack_from('<8I', b, 0)
    o = 32
    cmds, o = b[o:o + lcmd], o + lcmd
    args, o = b[o:o + larg], o + larg
    exp, o = b[o:o + lexp], o + lexp
    lnos, o = b[o:o + llno], o + llno
    return ncmd, cmds, args, exp, lnos


def verify_key(ff, files: list[Path], kcc, key: int) -> tuple[int, list[str]]:
    """Parse every YSTB with *key*; return (success count, failing names)."""
    ok = 0
    bad: list[str] = []
    for p in files:
        try:
            with open(p, 'rb') as fp:
                ff.YSTB(fp, kcc, key)
            ok += 1
        except Exception:
            bad.append(p.name)
    return ok, bad


def recover_key(ff, files: list[Path], kcc, ncmds: int, verbose: bool) -> int | None:
    """Recover the YSTB key from the binaries when no candidate key works.

    Each block is made of fixed size records (4 bytes for commands and line
    numbers, 12 for arguments), so every byte at index ``4*i + j`` is XORed
    with the same key byte.  Bytes that are nearly always zero in the plaintext
    (the high half of ``npar``/line numbers, the high half of ``kw_id``) expose
    three key bytes as the most common raw value; the last one is brute forced
    and the resulting keys are validated by really parsing the scripts.
    """
    if not files:
        return None
    try:
        secs = [read_sections(p) for p in files]
    except Exception:
        return None

    def mode(stream_idx: int, off: int, stride: int) -> int | None:
        cnt = Counter()
        for sec in secs:
            data = sec[stream_idx]
            if len(data) > off:
                cnt.update(data[off::stride])
        return cnt.most_common(1)[0][0] if cnt else None

    # cmds = <BBH (code, narg, npar)> and lno = <I, both end in 16 zero bits.
    k2, k3 = mode(1, 2, 4), mode(1, 3, 4)
    k1 = mode(2, 1, 12)
    if None in (k1, k2, k3):
        return None
    if verbose:
        print(f'  key bytes from the byte positions: k1={k1:#04x} '
              f'k2={k2:#04x} k3={k3:#04x} '
              f'(lno says {mode(4, 2, 4):#04x}/{mode(4, 3, 4):#04x})')

    code_bytes = {cmds[i] for _n, cmds, _a, _e, _l in secs
                  for i in range(0, len(cmds), 4)}
    cands = [((k0 << 24) | (k1 << 16) | (k2 << 8) | k3)
             for k0 in range(256)
             if all((b ^ k0) < ncmds for b in code_bytes)]
    if not cands:
        return None
    if verbose:
        print(f'  {len(cands)} candidate key(s) pass the command-code check')

    best, best_ok = None, -1
    for key in cands:
        ok, _bad = verify_key(ff, files, kcc, key)
        if verbose:
            print(f'  key 0x{key:08X}: {ok}/{len(files)} scripts parsed')
        if ok > best_ok:
            best, best_ok = key, ok
        if ok == len(files):
            break
    return best if best_ok > 0 else None


def resolve_key(ff, files: list[Path], kcc, ncmds: int, spec: str,
                verbose: bool) -> int:
    if spec.lower() != 'auto':
        try:
            key = int(spec, 0)
        except ValueError:
            die(f'--key must be a number such as 0x801DD23F or "auto", got {spec!r}')
        ok, bad = verify_key(ff, files, kcc, key)
        print(f'key 0x{key:08X}: {ok}/{len(files)} scripts parsed')
        if not ok:
            die('that key does not work, try --key auto to search for it')
        if bad:
            print(f'warning: {len(bad)} script(s) failed to parse, e.g. {bad[:3]}')
        return key

    for key in KNOWN_KEYS:
        ok, _bad = verify_key(ff, files, kcc, key)
        if ok == len(files):
            if verbose:
                print(f'known key 0x{key:08X} works ({ok}/{len(files)})')
            return key
    print('no known key matches, recovering it from the binaries ...')
    key = recover_key(ff, files, kcc, ncmds, verbose)
    if key is None:
        die('could not recover the YSTB key, pass it explicitly with --key')
    ok, bad = verify_key(ff, files, kcc, key)
    print(f'recovered key 0x{key:08X}: {ok}/{len(files)} scripts parsed')
    if bad:
        print(f'warning: {len(bad)} script(s) still fail, e.g. {bad[:3]}')
    return key


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #

def run_decompile(dc, indir: Path, odir: Path, key: int, i_enc: str,
                  verbose: bool) -> int:
    """Stage 1: rewrite the scripts as pseudo source with yuris_decompiler."""
    odir.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # yscd=None: no YSCom.ycd ships with the game, so compiler globals are
        # named I_comN and would have to be renamed by hand.
        dc.decompile(str(indir), str(odir), None, key,
                     i_encoding=i_enc, o_encoding='utf-8')
    lines = buf.getvalue().splitlines()
    if verbose:
        print('\n'.join(lines))
    nfile = sum(1 for l in lines if re.match(r'^\d+ ', l))
    print(f'[1/2] decompiled {nfile} script(s) -> {odir}')
    return nfile


def collect_text(ff, yscm, ystl, indir: Path, present: set[str], key: int,
                 i_enc: str, verbose: bool
                 ) -> tuple[list[tuple[int, str, int, str]], list[str]]:
    """Stage 2: return [(script_idx, script_path, line_no, text), ...].

    ``WORD`` is the only command that carries displayed text: the other string
    literals in the scripts are resource paths, UI captions or comparison
    operands (checked against ``yst_list.ybn``'s per script ``ntext`` counters).
    """
    word_code = next((i for i, c in enumerate(yscm.cmds) if c.name == TEXT_CMD), None)
    if word_code is None:
        die(f'this game has no {TEXT_CMD} command, cannot extract text')
    items: list[tuple[int, str, int, str]] = []
    failed: list[str] = []
    for scr in ystl.scrs:
        name = f'yst{scr.idx:0>5}.ybn'
        if name not in present:
            continue  # entries without a binary (nvar < 0) are empty scripts
        try:
            with open(indir / name, 'rb') as fp:
                ystb = ff.YSTB(fp, yscm.kcc, key, encoding=i_enc)
        except Exception as e:
            failed.append(f'{name} ({scr.path}): {type(e).__name__}: {e}')
            continue
        n = 0
        for cmd in ystb.cmds:
            if cmd.code != word_code or not cmd.args:
                continue
            s = cmd.args[0].dat
            if isinstance(s, str) and s:
                items.append((scr.idx, scr.path, cmd.lno, s))
                n += 1
        if verbose:
            print(f'  [{scr.idx:>3}] {scr.path} -> {n} text line(s)')
    return items, failed


def write_text(items, outdir: Path, with_lineno: bool) -> int:
    """Write the per script files, the combined file and the TSV index."""
    per_script: dict[tuple[int, str], list[tuple[int, str]]] = {}
    for idx, spath, lno, text in items:
        per_script.setdefault((idx, spath), []).append((lno, text))

    def fmt(lno: int, text: str) -> str:
        return f'[{lno}] {text}' if with_lineno else text

    root = outdir / 'text'
    for (_idx, spath), entries in per_script.items():
        dst = root / Path(*spath.replace('\\', '/').split('/'))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text('\n'.join(fmt(*e) for e in entries) + '\n',
                       encoding='utf-8', newline='\r\n')

    with open(outdir / 'all_text.txt', 'w', encoding='utf-8', newline='\r\n') as f:
        for (idx, spath), entries in per_script.items():
            f.write(f'===== [{idx}] {spath} ({len(entries)} lines) =====\n')
            f.writelines(fmt(*e) + '\n' for e in entries)
            f.write('\n')

    with open(outdir / 'text_index.tsv', 'w', encoding='utf-8-sig',
              newline='\r\n') as f:
        f.write('script_idx\tscript_path\tline_no\ttext\n')
        for idx, spath, lno, text in items:
            f.write(f'{idx}\t{spath}\t{lno}\t{text.replace(chr(9), " ")}\n')
    return len(per_script)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Extract dialogue text from a YU-RIS/E-Ris game (ysbin folder).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python extract_yuris_text.py --indir D:\\ysbin '
               '--outdir D:\\ysbin_text')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='folder with ysc.ybn/ysl.ybn/ysv.ybn/yst_list.ybn/yst*.ybn')
    ap.add_argument('--outdir', default='yuris_text_out',
                    help='output folder (default: ./yuris_text_out)')
    ap.add_argument('--repo', default=None,
                    help='path to the yuris_decompiler checkout '
                         '(default: ./yuris_decompiler next to this script)')
    ap.add_argument('--key', default='auto',
                    help='YSTB XOR key such as 0x801DD23F, or "auto" (default) to '
                         'try the known keys and recover it if none works')
    ap.add_argument('--i-encoding', default='cp932', help='script text encoding')
    ap.add_argument('--no-decompile', action='store_true',
                    help='skip stage 1 and only extract the text')
    ap.add_argument('--with-lineno', action='store_true',
                    help='prefix every text line with its script line number')
    ap.add_argument('-v', '--verbose', action='store_true',
                    help='print per script progress and key recovery details')
    args = ap.parse_args(argv)

    indir = Path(args.indir).expanduser()
    outdir = Path(args.outdir).expanduser()
    if not indir.is_dir():
        die(f'input folder not found: {indir}')
    if not (indir / 'ysc.ybn').is_file():
        hint = ''
        if list(indir.glob('*.ypf')):
            hint = (' - this folder only holds .ypf archives, unpack them first '
                    'with yuris_decompiler.YPF')
        die(f'{indir / "ysc.ybn"} not found{hint}')
    repo = (Path(args.repo).expanduser() if args.repo
            else Path(__file__).resolve().parent / 'yuris_decompiler')
    ff, dc = load_yurislib(repo)

    ver = detect_version(ff, indir)
    files = ystb_files(indir)
    print(f'input : {indir} (version {ver}, {len(files)} scripts)')
    print(f'output: {outdir}')

    with open(indir / 'ysc.ybn', 'rb') as fp:
        yscm = ff.YSCM(ff.Rdr(fp.read(), enc=args.i_encoding))
    with open(indir / 'yst_list.ybn', 'rb') as fp:
        ystl = ff.YSTL(ff.Rdr(fp.read(), enc=args.i_encoding))

    key = resolve_key(ff, files, yscm.kcc, len(yscm.cmds), args.key, args.verbose)

    if not args.no_decompile:
        run_decompile(dc, indir, outdir / 'decompiled', key, args.i_encoding,
                      args.verbose)

    items, failed = collect_text(ff, yscm, ystl, indir, {p.name for p in files},
                                 key, args.i_encoding, args.verbose)
    if failed:
        print(f'warning: {len(failed)} script(s) could not be parsed:')
        for m in failed[:5]:
            print(f'  {m}')
    if not items:
        die('no text found - wrong key or wrong input folder?')
    outdir.mkdir(parents=True, exist_ok=True)
    nscripts = write_text(items, outdir, args.with_lineno)
    njp = sum(1 for _i, _p, _l, t in items if JP_RE.search(t))
    print(f'[2/2] extracted {len(items)} text line(s) from {nscripts} script(s), '
          f'{njp} with Japanese characters')
    print(f'      {outdir / "text"}          one file per script')
    print(f'      {outdir / "all_text.txt"}   all text in one file')
    print(f'      {outdir / "text_index.tsv"} index (script, line, text)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
