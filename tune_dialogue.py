#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Change the dialogue's face and size in one command.

Tuning used to be a long conversation of one-off probes - install a font,
measure it, rebuild the pack, install it, look at the result, repeat.  The
measurements say none of that work is actually slow: a full pack rebuild is
about 26 s (inject 6 s, engine scripts 10 s, pack 1 s, verify 8 s) and a font
install with its fresh-process verification is about 51 s.  What made it take
an hour was walking there in hundreds of small steps, most of them spent
re-discovering how the engine sizes a glyph.

So this script is the whole loop, and it skips every phase whose inputs have
not changed since the last run (recorded in ``build\\tune_state.json``)::

    python tune_dialogue.py --size "M=30x32, NAME=30x32" --game "<game folder>"
    python tune_dialogue.py --size "M=32x34"        # size only: ~26 s, no font work
    python tune_dialogue.py --weight light --bold-weight light   # weight only: ~30 s
    python tune_dialogue.py --preview-sizes 30,32,34 --preview-only   # ~20 s

Both weight slots have to be changed together: the engine's font builder
(oujunoshima.exe 0x4425d4) asks GDI for lfWeight 400 or 700 depending on a flag
it gets from the script, so putting the thin face only in the 400 slot leaves
the 700 branch untouched - see section 8.4 of glossary/STYLE_GUIDE.md.

    [font]   install_glow_sans.py    only when the weight or the metrics changed
    [build]  build_cn_pack.py        inject -> re-encode -> pack -> verify -> install
    [look]   preview_yuris_font.py   PNG through the engine's own GDI pipeline

``--preview-only`` draws the pictures and touches nothing, which is the cheapest
way to pick a size in the first place: the pictures are rendered at the exact
lfHeight and pen advance the game would use, so a size can be judged before any
file is installed.  ``--force`` ignores the state and redoes everything.

The sizes are the operands of ``es.TD.SIZE.SET``: the pen advance and the glyph
height.  The renderer adds the letter spacing (``gInt1144(36,19)``, the game
ships -2) to every advance, which is what the preview uses as its pitch; the
speaker plate is drawn without that letter spacing, so its pitch is its own
advance (see ``es.TX.NAME.SHOW.TX`` in ``eris\\es_text.yst``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

try:
    import build_cn_pack
    import install_glow_sans as igs
    import preview_yuris_font as pv
    import transcode_yuris_scripts as tsc
except ImportError:  # pragma: no cover
    print('error: tune_dialogue.py must live next to install_glow_sans.py, '
          'build_cn_pack.py, preview_yuris_font.py and '
          'transcode_yuris_scripts.py', file=sys.stderr)
    raise SystemExit(1)

#: What ``userdefine\\メイン定義.txt`` ships, i.e. the spacing a preview has to
#: assume when the caller does not name one: 字間 -2 px, 行間 0 px.
SHIPPED_CHAR_SPACE = -2
SHIPPED_LINE_SPACE = 0

#: The face the Japanese release draws with - the yardstick for every preview.
REFERENCE_FACE = 'ＭＳ ゴシック'


def sha256(path: Path) -> str:
    """Full-file digest, used to tell "the pack is already installed" apart
    from "the pack is installed but stale"."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class Steps:
    """Wall time per phase - the point of the whole script is that these are
    small, so the run prints them instead of looking slow."""

    def __init__(self) -> None:
        self.marks: list[tuple[str, float]] = []
        self._t = time.perf_counter()

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self.marks.append((label, now - self._t))
        self._t = now

    def report(self) -> None:
        print('timing: ' + ', '.join(f'{label} {secs:.1f}s'
                                     for label, secs in self.marks)
              + f' (total {sum(s for _l, s in self.marks):.1f}s)')


def read_state(path: Path) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write('\n')


def td_spec(sizes: dict[str, tuple[int, int]]) -> str:
    """``{'M': (30, 32)}`` -> ``'M=30x32'``, the spelling ``--td-size`` takes."""
    return ', '.join(f'{name}={w}x{h}' if w != h else f'{name}={w}'
                     for name, (w, h) in sorted(sizes.items()))


def font_step(args, state: dict, steps: Steps) -> bool:
    """Install the font unless the installed pair is already this one."""
    want = {'weight': args.weight.lower(), 'bold_weight': args.bold_weight.lower(),
            'line_metrics': args.line_metrics, 'family': args.family}
    installed = [Path(igs.FONT_DIR) / name for name, _w, _b in igs.SLOTS]
    if (not args.force and state.get('font') == want
            and all(p.is_file() for p in installed)):
        print(f'font   : {want["weight"]}/{want["line_metrics"]} already '
              f'installed, skipping (--force to redo)')
        steps.mark('font(skipped)')
        return True
    argv = ['--weight', args.weight, '--bold-weight', args.bold_weight,
            '--family', args.family, '--line-metrics', args.line_metrics]
    if igs.main(argv) != 0:
        return False
    state['font'] = want
    steps.mark('font')
    return True


def pack_step(args, state: dict, sizes, out: Path, game: Path | None,
              steps: Steps) -> bool:
    """Rebuild (and optionally install) the pack, or prove it is still current."""
    want = {'size': {k: list(v) for k, v in sorted(sizes.items())},
            'char_space': args.char_space, 'line_space': args.line_space}
    pack = out / 'update1.ypf'
    rebuild = args.force or state.get('pack') != want or not pack.is_file()
    if rebuild:
        argv = ['--workpack', args.workpack, '--indir', args.indir,
                '--out', str(out), '--td-size', td_spec(sizes)]
        if args.char_space is not None:
            argv += ['--char-space', str(args.char_space)]
        if args.line_space is not None:
            argv += ['--line-space', str(args.line_space)]
        if game:
            argv += ['--install', '--install-dir', str(game)]
        if build_cn_pack.main(argv) != 0:
            return False
        state['pack'] = want
        steps.mark('build')
    else:
        print(f'build  : {td_spec(sizes)} already built, skipping the rebuild '
              f'(--force to redo)')
        steps.mark('build(skipped)')

    if game:
        built = sha256(pack)
        for target in (game / 'update1.ypf', game / 'pac' / 'update1.ypf'):
            if target.is_file() and sha256(target) == built:
                print(f'install: {target} is already this pack')
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pack.read_bytes())
            print(f'install: copied to {target}')
        steps.mark('install')
    else:
        print('install: no --game given, nothing was copied into the game')
    return True


NAME_REJECT = '。、！？…「」『』（）—―‐·，,:;'


def pick_name(rows_path: Path, lang: str) -> str:
    """A short translated line: in this game the 2-6 character ones are the
    speaker names, which is what the name plate preview needs."""
    try:
        rows = pv.load_lines(str(rows_path))
    except OSError:
        return pv.SAMPLES[lang]
    for orig, new in rows:
        txt = pv._clean(new if (lang == 'cn' and new.strip()) else orig, lang)
        txt = txt.strip().strip('“”"\'')
        if 2 <= len(txt) <= 6 and not any(c in txt for c in NAME_REJECT):
            return txt
    return pv.SAMPLES[lang]


def preview_step(args, sizes, out: Path, steps: Steps) -> list[Path]:
    """Render what the game would draw, before anything is installed."""
    made: list[Path] = []
    char_space = (SHIPPED_CHAR_SPACE if args.char_space is None
                  else args.char_space)
    dialogue = sizes.get('M') or sizes.get('MSG')
    if dialogue:
        adv, height = dialogue
        png = out / f'tune_M{adv}x{height}.png'
        print(f'preview: dialogue, lfHeight {height}, pen advance '
              f'{adv}{char_space:+d} = {adv + char_space} px -> {png}')
        pv.main(['--faces', f'{igs.FAMILY_DEFAULT},{REFERENCE_FACE}',
                 '--sizes', str(height), '--pitch', str(adv + char_space),
                 '--lang', args.lang, '--out', str(png), '--zoom', str(args.zoom),
                 '--no-coverage'])
        made.append(png)
    plate = sizes.get('NAME')
    if plate:
        adv, height = plate
        png = out / f'tune_NAME{adv}x{height}.png'
        print(f'preview: name plate, lfHeight {height}, pen advance {adv} px '
              f'(the plate is drawn without the letter spacing) -> {png}')
        pv.main(['--faces', f'{igs.FAMILY_DEFAULT},{REFERENCE_FACE}',
                 '--sizes', str(height), '--pitch', str(adv), '--lang', args.lang,
                 '--text', pick_name(Path(args.workpack) / 'lines.tsv',
                                     args.lang),
                 '--out', str(png), '--zoom', str(args.zoom), '--no-coverage'])
        made.append(png)
    steps.mark('preview')
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python tune_dialogue.py --size "M=32x33, NAME=32x32" '
               '--game "<game folder>"')
    ap.add_argument('--size', default='', metavar='NAME=SIZE',
                    help='text definitions to resize: "M" is the dialogue, '
                         '"NAME" the speaker plate.  A size is one number for a '
                         'square cell or WIDTHxHEIGHT for the pen advance and the '
                         'glyph height separately, e.g. "M=30x32, NAME=30x32"')
    ap.add_argument('--weight', default=None,
                    help='Glow Sans weight for the regular slot: '
                         + ', '.join(sorted(igs.WEIGHTS)))
    ap.add_argument('--bold-weight', default='bold',
                    help='Glow Sans weight for the bold slot (default: bold)')
    ap.add_argument('--line-metrics', default=igs.LINE_METRICS_DEFAULT,
                    metavar='typo|keep|ASC/DESC',
                    help=f'vertical metrics of the installed font (default: '
                         f'{igs.LINE_METRICS_DEFAULT}); this is what decides how '
                         f'large a glyph comes out for a given script size')
    ap.add_argument('--family', default=igs.FAMILY_DEFAULT,
                    help=f'family to install and point the scripts at '
                         f'(default: {igs.FAMILY_DEFAULT!r})')
    ap.add_argument('--char-space', type=int, default=None, metavar='PIXELS',
                    help=f'letter spacing (gInt1144(36,19)); the game ships '
                         f'{SHIPPED_CHAR_SPACE}, i.e. what the preview assumes '
                         f'when this is not given')
    ap.add_argument('--line-space', type=int, default=None, metavar='PIXELS',
                    help=f'line spacing (gInt1144(36,20)); the game ships '
                         f'{SHIPPED_LINE_SPACE}')
    ap.add_argument('--game', default=None,
                    help='game folder to install into; without it the pack is '
                         'only built')
    ap.add_argument('--workpack', default='workpack')
    ap.add_argument('--indir', default=r'D:\ysbin')
    ap.add_argument('--out', default='build')
    ap.add_argument('--preview-sizes', default=None,
                    help='with --preview-only: comma separated glyph heights to '
                         'compare, e.g. 30,32,34 (pen advances default to the '
                         'same number, or --char-space apart)')
    ap.add_argument('--preview-only', action='store_true',
                    help='draw the comparison pictures and change nothing')
    ap.add_argument('--no-preview', action='store_true',
                    help='skip the pictures when a change is applied')
    ap.add_argument('--text', default=None,
                    help='sample line for the preview (\\n for line breaks)')
    ap.add_argument('--lang', choices=('cn', 'jp'), default='cn')
    ap.add_argument('--zoom', type=int, default=2)
    ap.add_argument('--force', action='store_true',
                    help='ignore the recorded state: redo the font and the build')
    args = ap.parse_args(argv)

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / 'tune_state.json'
    steps = Steps()

    if args.preview_only:
        if not args.preview_sizes:
            print('error: --preview-only wants --preview-sizes 30,32,34',
                  file=sys.stderr)
            return 2
        made = []
        for height in (int(s) for s in args.preview_sizes.split(',') if s.strip()):
            adv = height + (args.char_space if args.char_space is not None
                            else SHIPPED_CHAR_SPACE)
            png = out / f'tune_only{height}.png'
            print(f'preview: lfHeight {height}, pen advance {adv} px -> {png}')
            pv.main(['--faces', f'{igs.FAMILY_DEFAULT},{REFERENCE_FACE}',
                     '--sizes', str(height), '--pitch', str(adv),
                     '--lang', args.lang, '--out', str(png),
                     '--zoom', str(args.zoom), '--no-coverage']
                    + (['--text', args.text] if args.text else []))
            made.append(png)
        steps.mark('preview')
        steps.report()
        for p in made:
            print(f'  {p}')
        return 0

    if not args.size and args.weight is None:
        print('error: nothing to do - pass --size, --weight or --preview-only',
              file=sys.stderr)
        return 2

    sizes: dict[str, tuple[int, int]] = {}
    if args.size:
        try:
            sizes = tsc.parse_td_sizes(args.size)
        except ValueError as exc:
            print(f'error: --size {args.size!r}: {exc}', file=sys.stderr)
            return 2

    state = read_state(state_path)
    game = Path(args.game).expanduser() if args.game else None
    if game and not game.is_dir():
        print(f'error: {game} is not a folder', file=sys.stderr)
        return 2

    if args.weight is not None and not font_step(args, state, steps):
        return 1
    if sizes:
        if not pack_step(args, state, sizes, out, game, steps):
            return 1
    if not args.no_preview:
        show = sizes or {k: tuple(v) for k, v in
                         (state.get('pack', {}).get('size') or {}).items()}
        preview_step(args, show or {'M': (30, 32)}, out, steps)

    write_state(state_path, state)
    steps.report()
    print(f'recorded in {state_path}; run again with the same numbers and '
          f'nothing but the previews is repeated')
    if game:
        print('restart the game and look at the dialogue; pass --force to redo '
              'a phase that was skipped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
