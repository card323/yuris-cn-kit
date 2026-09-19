#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a Chinese ``update1.ypf`` from a translation work package.

Pipeline::

    workpack/lines.tsv + workpack/usages.tsv
        -> injection template
        -> inject_yuris_text.py --apply          (rebuild the 51 scripts)
        -> transcode_yuris_scripts.py            (re-encode the engine scripts)
        -> ypf_tool build                        (pack them into update1.ypf)
        -> verify_cn_pack.py                     (prove the pack is correct)
        -> copy next to the exe and into pac/    (--install)

Every line that still has an empty ``new_text`` is filled with the original
Japanese re-encoded from CP932 into GBK (the four characters with no GBK
mapping are substituted, see ``transcode_yuris_gbk.py``).  So a half finished
translation still produces a game in which nothing is mojibake - untranslated
lines simply stay Japanese.

The engine's own scripts (index 0..181: the menus, the system messages, the
punctuation metrics, the ruby delimiters) live in the same archives as the
scenario scripts and are still CP932, while the pack now hands the engine GBK
text.  That mix is what made dialog boxes and comparison targets come out as
mojibake, so the same pass re-encodes those scripts too - byte for byte in
place, leaving resource names alone, renaming the font face to ``--face`` and
writing the text sizes ``--td-size`` asks for (``M`` is the dialogue the ADV
screen draws; the menus and the system text keep their own sizes).  A size is
either one number for a square cell or ``WIDTHxHEIGHT`` - the renderer advances
the pen by the width and draws the glyphs at the height, so a face whose ink is
wide for its advance wants a narrower cell than it is tall.  The same pass writes
the spacing ``--char-space``/``--line-space`` ask for (``gInt1144(36,19)`` and
``(36,20)``, the pixels the renderer adds between two characters and between two
lines - the only lever there is, and it is global).
``transcode_yuris_scripts.py`` does that work and refuses to write a script it
cannot prove is still layout-identical.  It leaves one family of strings alone:
the text an **OS dialog box** shows (``DIALOG`` arguments, calls into the dialog
wrappers, and the confirm-definition script).  Windows draws those with the
process code page - 932 in this game - rather than with the font's character
set, so re-encoding them is what made the confirm boxes come out as mojibake.
``--no-engine-scripts`` skips the whole pass.

The finished pack is verified before anything is installed: the pack must hold
exactly the rebuilt scripts, every string must decode back out of the built
bytes with the Windows code page 936 table, the branch/layout blocks must still
match the originals, and the dialog text must still hold its original CP932
bytes.  Pass ``--no-verify`` to skip that step.

Nothing is written to the game folder unless ``--install`` is passed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

try:
    import inject_yuris_text as inj
    import transcode_yuris_gbk as tg
    import transcode_yuris_scripts as tsc
    import ypf_tool
except ImportError:  # pragma: no cover
    print('error: build_cn_pack.py must live next to inject_yuris_text.py, '
          'transcode_yuris_gbk.py, transcode_yuris_scripts.py and ypf_tool.py',
          file=sys.stderr)
    raise SystemExit(1)


class Clock:
    """Wall time per build phase, printed as one line at the end.

    A rebuild is re-injected, re-encoded, re-packed and re-verified from
    scratch on every tweak, so which phase dominates is what decides whether a
    change is cheap (font weight: no rebuild at all) or expensive.
    """

    def __init__(self) -> None:
        self.marks: list[tuple[str, float]] = []
        self._t = time.perf_counter()

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self.marks.append((label, now - self._t))
        self._t = now

    def report(self) -> None:
        total = sum(seconds for _l, seconds in self.marks)
        print('phase times: '
              + ', '.join(f'{label} {seconds:.1f}s'
                          for label, seconds in self.marks)
              + f' (total {total:.1f}s)')


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        header = f.readline().rstrip('\r\n').split('\t')
        rows = []
        for line in f:
            line = line.rstrip('\r\n')
            if not line:
                continue
            cells = line.split('\t')
            if len(cells) > len(header):
                cells = cells[:len(header) - 1] + \
                    ['\t'.join(cells[len(header) - 1:])]
            cells += [''] * (len(header) - len(cells))
            rows.append(dict(zip(header, cells)))
    return header, rows


def _check_face(face: str) -> None:
    """Warn when the face the pack names is not installed on this machine.

    GDI does not report a missing face, it silently hands out a substitute, and
    that substitution is what makes the strokes look uneven - so a pack built
    for a face this machine does not have looks fine in every check that does not
    actually draw something.
    """
    try:
        import preview_yuris_font as pf
        faces = pf.installed_faces()
    except Exception as e:                       # pragma: no cover
        print(f'note: could not list the installed fonts ({type(e).__name__}), '
              f'the face {face!r} was not checked')
        return
    if face.upper() not in faces:
        print(f'warning: no font named {face!r} is installed - Windows will '
              f'substitute another face and the strokes will look uneven; run '
              f'install_glow_sans.py first', file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Build the Chinese update1.ypf from a work package.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r'example: python build_cn_pack.py --workpack workpack '
               r'--out build --install '
               r'--install-dir "D:\path\to\game"')
    ap.add_argument('--workpack', default='workpack',
                    help='folder holding lines.tsv and usages.tsv '
                         '(default: ./workpack)')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='the original script folder to inject into')
    ap.add_argument('--out', default='build',
                    help='output folder (default: ./build)')
    ap.add_argument('--repo', default=None,
                    help='path to the yuris_decompiler checkout')
    ap.add_argument('--key', default='auto',
                    help='YSTB XOR key such as 0x801DD23F, or "auto" (default)')
    ap.add_argument('--encoding', default='gbk',
                    help='encoding of new_text / of the built pack '
                         '(default: gbk)')
    ap.add_argument('--no-fallback', action='store_true',
                    help='do not transcode untranslated lines - they stay '
                         'CP932 and will look like mojibake')
    ap.add_argument('--no-substitute', action='store_true',
                    help='refuse the four characters with no GBK mapping '
                         'instead of substituting them')
    ap.add_argument('--no-engine-scripts', action='store_true',
                    help='pack the original CP932 engine scripts instead of '
                         're-encoding them (menus and system text stay mojibake)')
    ap.add_argument('--face', default=tsc.FACE_TARGET,
                    help=f'font face the engine scripts are pointed at '
                         f'(default: {tsc.FACE_TARGET!r}); it has to be a face '
                         f'this machine really has, see install_glow_sans.py.  '
                         f'Pass an empty string to keep the original name')
    ap.add_argument('--td-size', default='', metavar='NAME=SIZE',
                    help='resize the named text definitions of '
                         'userdefine\\文字定義.txt, as NAME=SIZE pairs separated '
                         'by commas or spaces (e.g. "M=30x38"): "M" is the dialogue '
                         'the ADV screen draws, "NAME" the speaker plate, and '
                         'every menu and system definition keeps its size.  A size '
                         'is the character cell in pixels - one number for a square '
                         'cell, or WIDTHxHEIGHT for the pen advance and the glyph '
                         'height separately')
    ap.add_argument('--char-space', type=int, default=None, metavar='PIXELS',
                    help='pixels the renderer adds between two characters '
                         '(gInt1144(36,19), the letter spacing): a negative value '
                         'tightens the text, and a wide face whose glyphs leave '
                         'gaps wants around -6 where the game ships -2')
    ap.add_argument('--line-space', type=int, default=None, metavar='PIXELS',
                    help='pixels the renderer adds between two lines '
                         '(gInt1144(36,20), the line spacing); the game ships 0')
    ap.add_argument('--no-verify', action='store_true',
                    help='skip the verify_cn_pack.py safety check after building')
    ap.add_argument('--install', action='store_true',
                    help='copy update1.ypf next to the game exe and into pac\\')
    ap.add_argument('--install-dir', default=None,
                    help='the game folder (required with --install)')
    ap.add_argument('--level', type=int, default=9,
                    help='zlib level for the archive (default 9)')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args(argv)

    clock = Clock()

    if args.install and not args.install_dir:
        print('error: --install needs --install-dir <game folder>',
              file=sys.stderr)
        return 2

    wp = Path(args.workpack).expanduser()
    for name in ('lines.tsv', 'usages.tsv'):
        if not (wp / name).is_file():
            print(f'error: {wp / name} not found', file=sys.stderr)
            return 2
    _lh, lines = read_tsv(wp / 'lines.tsv')
    _uh, usages = read_tsv(wp / 'usages.tsv')

    text: dict[str, str] = {}
    original: dict[str, str] = {}
    for row in lines:
        text[row['id']] = row.get('new_text', '')
        original[row['id']] = row.get('orig_text', '')

    out = Path(args.out).expanduser()
    overlay = out / 'ysbin'
    overlay.mkdir(parents=True, exist_ok=True)
    # Both writers below only *add* to the overlay, so a file that an earlier
    # build re-encoded and this one no longer touches would survive and be packed
    # in its stale form.  Clear it out first: the overlay holds nothing but the
    # scripts this build produced.
    stale = sorted(overlay.glob('*.ybn'))
    for p in stale:
        p.unlink()
    if stale:
        print(f'cleared {len(stale)} old script(s) from {overlay}')
    template = out / 'inject_input.tsv'
    filled = skipped = fallback = 0
    subs: dict[str, int] = {}
    from_translation: dict[str, int] = {}
    rows: list[tuple[str, tuple[str, ...]]] = []

    for row in usages:
        i = row['id']
        orig = original.get(i, '')
        new = text.get(i, '')
        translated = bool(new)
        if translated:
            filled += 1
        elif args.no_fallback:
            skipped += 1
            continue
        else:
            new = orig
            fallback += 1
        new, hits = tg.substitute(new)
        for ch, n in hits.items():
            subs[ch] = subs.get(ch, 0) + n
            if translated:
                from_translation[ch] = from_translation.get(ch, 0) + n
        rows.append((i, (row.get('script_idx', ''), row['script_file'],
                         row.get('cmd_index', ''), row.get('line_no', ''),
                         row.get('script_path', ''), args.encoding,
                         inj.clean(orig), inj.clean(new))))

    bad: list[tuple[str, str]] = []
    seen: dict[str, bool] = {}
    for i, cells in rows:
        for ch in cells[7]:
            if ch in seen:
                continue
            seen[ch] = tg.windows_cp936_can_encode(ch)
            if not seen[ch]:
                bad.append((i, ch))
    if bad:
        print(f'error: {len(bad)} line(s) hold a character the engine can not '
              f'show (code page 936)', file=sys.stderr)
        for i, ch in bad[:20]:
            print(f'    line id {i}: {ch!r} (U+{ord(ch):04X})', file=sys.stderr)
        return 2

    with open(template, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(inj.TEMPLATE_HEADER + '\r\n')
        for _i, cells in rows:
            f.write('\t'.join(cells) + '\r\n')

    print(f'{len(usages)} occurrence(s): {filled} translated, {fallback} kept '
          f'in Japanese, {skipped} left out')
    if subs:
        for ch, n in sorted(subs.items(), key=lambda kv: -kv[1]):
            print(f'    substituted {ch} (U+{ord(ch):04X}) -> '
                  f'{tg.SUBSTITUTIONS[ch]}  x{n}'
                  + (f'  ({from_translation[ch]} from a translation)'
                     if ch in from_translation else ''))
    if args.no_substitute and from_translation:
        print('error: --no-substitute is on but the translation uses '
              'characters with no GBK mapping', file=sys.stderr)
        for ch, n in sorted(from_translation.items(), key=lambda kv: -kv[1]):
            print(f'    {ch!r} (U+{ord(ch):04X}) x{n} - write '
                  f'{tg.SUBSTITUTIONS[ch]!r} instead', file=sys.stderr)
        return 2

    rc = inj.main(['--indir', args.indir, '--outdir', str(overlay),
                   '--apply', str(template), '--encoding', args.encoding,
                   '--report', str(out / 'inject_report.tsv')]
                  + (['--repo', args.repo] if args.repo else [])
                  + (['--key', args.key] if args.key != 'auto' else []))
    if rc != 0:
        return rc
    clock.mark('inject')

    # The engine scripts go into the same overlay, so injection and the
    # transcode cannot overwrite each other's work: they own disjoint index
    # ranges (userscripts above DEFAULT_MAX_IDX vs. the engine below it).
    if not args.no_engine_scripts:
        rc = tsc.main(['--indir', args.indir, '--outdir', str(overlay),
                       '--encoding', args.encoding,
                       '--max-idx', str(tsc.DEFAULT_MAX_IDX),
                       '--face', args.face,
                       '--td-size', args.td_size,
                       '--report', str(out / 'engine_report.tsv')]
                      + (['--char-space', str(args.char_space)]
                         if args.char_space is not None else [])
                      + (['--line-space', str(args.line_space)]
                         if args.line_space is not None else [])
                      + (['--repo', args.repo] if args.repo else [])
                      + (['--key', args.key] if args.key != 'auto' else [])
                      + (['--verbose'] if args.verbose else []))
        if rc != 0:
            return rc
        if args.face:
            _check_face(args.face)
    clock.mark('engine scripts')

    entries: list[dict] = []
    for p in sorted(overlay.glob('*.ybn')):
        entries.append({'name': 'ysbin\\' + p.name, 'raw': p.read_bytes()})
    if not entries:
        print('error: no script was rebuilt - nothing to pack', file=sys.stderr)
        return 1
    data = ypf_tool.build(entries, 500, dedup=False, level=args.level)
    ypf = out / 'update1.ypf'
    ypf.write_bytes(data)
    _ver, back = ypf_tool.read_ypf(data)
    ok = len(back) == len(entries) and all(
        b['name'] == e['name'] and b['raw'] == e['raw']
        for b, e in zip(back, entries))
    print(f'wrote {ypf} ({len(data)} byte(s), {len(entries)} entrie(s))')
    print('  re-read check:', 'OK' if ok else 'FAILED')
    clock.mark('pack')
    if not ok:
        return 1

    if not args.no_verify:
        import verify_cn_pack
        print('verifying the pack against the original scripts ...')
        rc = verify_cn_pack.main(
            [str(out), args.indir]
            + (['--repo', args.repo] if args.repo else [])
            + (['--key', args.key] if args.key != 'auto' else [])
            + (['--verbose'] if args.verbose else []))
        if rc != 0:
            print('error: the pack did not verify - not installing anything',
                  file=sys.stderr)
            return rc
        clock.mark('verify')

    clock.report()

    if args.install:
        game = Path(args.install_dir).expanduser()
        if not game.is_dir():
            print(f'error: {game} is not a folder', file=sys.stderr)
            return 2
        for target in (game / 'update1.ypf', game / 'pac' / 'update1.ypf'):
            shutil.copyfile(ypf, target)
            print(f'  installed {target} ({target.stat().st_size} byte(s))')
        print('relaunch the game to see the new text; delete or rename '
              'update1.ypf to go back to the originals')
    else:
        print('not installed - pass --install --install-dir "<game folder>" '
              'to copy it into the game')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
