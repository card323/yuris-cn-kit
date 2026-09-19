#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write a translation work package for a YU-RIS (E-Ris) script set.

Two files come out, both UTF-8:

``lines.tsv``
    the text to translate, deduplicated - one row per distinct line::

        id  count  chars  orig_text  new_text

    ``id``        stable line number (first appearance order), used to join
    ``count``     how many places in the game say exactly this
    ``chars``     character budget - the original length, see below
    ``orig_text`` the original text, **verbatim**, nothing substituted
    ``new_text``  empty, this is what a translator fills in

``usages.tsv``
    every occurrence of every line, in game order::

        id  script_idx  script_file  cmd_index  line_no  script_path

``scripts.tsv``
    the scripts that hold text, in index order::

        script_idx  script_file  script_path  lines

``README.txt``
    the same instructions for the translator, in the package itself.

The extraction is faithful to the original bytes: ``orig_text`` is the CP932
text decoded as-is and the file is written as UTF-8, so it round trips exactly.
Nothing is normalised, replaced or dropped - the substitutions the game needs
(U+226A/U+226B/U+30FB/U+266A have no GBK mapping) happen later, only when the
pack is built, and are visible in that build's report.

``chars`` matters because the engine wraps text by counting *bytes* and the
dialogue boxes are a fixed size.  A kana is two bytes in both CP932 and GBK and
a kanji is two bytes in both, so a translation with the same number of
characters as ``orig_text`` occupies exactly the same box.  Longer is usually
fine, much longer overflows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import inject_yuris_text as inj
except ImportError:  # pragma: no cover
    print('error: make_translation_workpack.py must live next to '
          'inject_yuris_text.py', file=sys.stderr)
    raise SystemExit(1)

LINES_HEADER = ('id', 'count', 'chars', 'orig_text', 'new_text')
USAGES_HEADER = ('id', 'script_idx', 'script_file', 'cmd_index', 'line_no',
                 'script_path')
SCRIPTS_HEADER = ('script_idx', 'script_file', 'script_path', 'lines')

README = """\
Translation work package - YU-RIS (E-Ris) script set
===================================================

Files
-----
lines.tsv     the text to translate, one row per DISTINCT line - UTF-8
                id         stable line number, never change it
                count      how many places in the game say exactly this line
                chars      character budget: the length of the original line
                orig_text  the original text, verbatim (CP932, decoded as-is)
                new_text   <- the only column to edit
usages.tsv    where each line of lines.tsv is used, in game order
                id  script_idx  script_file  cmd_index  line_no  script_path
              script_path is the per-scene source name, so you can tell which
              scenes a line belongs to.
scripts.tsv   the scripts that hold text, with their scene names
README.txt    this file

How to fill it in
-----------------
* Edit new_text only. Leave a row empty to keep that line in Japanese: it is
  re-encoded at build time, so a partly translated build still shows readable
  text everywhere instead of mojibake.
* Save as UTF-8. Keep tabs and line breaks out of the cells.
* Keep the speaker name AND its mark in front of the quote verbatim.  A line like
  ``カノ「おはよう……」`` carries the name INSIDE the text; the engine cuts it
  out and draws it on the name plate only when the line starts with a registered
  name (74 registrations, 63 distinct, in userdefine\\キャラ名定義.txt) that is
  immediately followed by one of the 3 registered marks: 「 for dialogue, 『 for
  inner speech, （ for thoughts.  Translate the part after the mark and leave
  ``カノ「`` exactly as it is - including WHICH mark the original used, because
  ``カノ“…”`` is not recognised at all.  This is the agreed policy - the name
  plates stay Japanese; only the dialogue is Chinese.  If you change the prefix or
  the mark, the name is painted into the dialogue box instead of the name plate.
  Only the 4 staff-comment lines use 「」 as an ordinary quotation mark and have no
  prefix.
* Ruby markup (``≪base／reading≫``) may be dropped entirely when the reading is
  only a pronunciation guide, but keep the ``≪x／・≫`` per-character emphasis
  spans (each covers exactly one character) if you want to preserve the
  emphasis, and never invent new ones.  Do not use ≪ ≫ for ordinary quotes.
* Try to stay near the chars budget. The wrap width comes from the dialogue
  control itself (790 px wide, 40 px of margin), not from a constant, and the
  tuned dialogue font steps 28 px per character, so one line holds about 26
  fullwidth characters and the box shows 5 lines; anything longer is paginated
  by the engine, not cut off. Kana, kanji and fullwidth punctuation are 2 bytes
  in both CP932 and GBK, so a translation of roughly the same length fits the
  same box - a translation more than ~20% longer than the original is worth
  shortening.
* Four characters have no mapping in the engine's code page (936) and are
  replaced automatically when the pack is built:
      U+226A -> U+300A     U+226B -> U+300B
      U+30FB -> U+00B7     U+266A -> U+3002
  The angle bracket and middle dot replacements keep the look of the original,
  and the engine scripts are re-encoded with the same replacements, so the ruby
  delimiters they define still match the text. The build report lists how many
  of each it swapped.
* The build refuses to run if any other character can not be shown by code page
  936; it names the offending line ids. Fix those lines and build again.

Glossary and the pre-build check
--------------------------------
glossary\\glossary.tsv (one folder up) is the termbase: cat, orig, reading, cn
(the agreed Chinese term), note, count. Use its cn column for every character,
place, technique and H-scene word it lists; glossary\\STYLE_GUIDE.md (Chinese)
explains the register, the punctuation rules and the gikun cases.

Run the checker as often as you like - it is offline and needs no build:

    python ..\\check_glossary.py --lines lines.tsv
    python ..\\check_glossary.py --lines lines.tsv --strict     (warnings fail too)

It reports, per line id: characters code page 936 can not hold, a line whose
name + mark no longer matches the cut rule the engine uses, a plate the
translation adds where the original had none, broken ruby markup, more than 64
ruby spans on a line, an emphasis span covering more than one character, a
translation much wider than the original, and terms spelled differently from
glossary.tsv.  Exit code 0 = pass, 1 = errors, 2 = a file could not be read.

Working from the per-scene files
--------------------------------
The scenes are kept one folder up in translation\\userscript, one ``<scene>_中文.txt``
per script, so they can be merged into new_text with

    python ..\\merge_translation.py --apply

Line N of a scene file is line N of that scene in lines.tsv.  The merge asserts
the line counts match and skips a scene that does not, so one half-finished file
can not shift every row after it.  When a line is translated differently in
several scenes the first scene wins and the clash is printed for you to pick
from.  Without --apply it only reports.

If a prefix was translated by mistake, put it back mechanically:

    python ..\\fix_name_plates.py            dry run - prints what it would change
    python ..\\fix_name_plates.py --apply    rewrites the scene files, keeps .bak

It reads the name and the mark back out of the aligned Japanese original, so
``文鸣“为什么”`` becomes ``文鳴（为什么……）`` again, and it is safe to run twice.

The font
--------
The pack ships no font; it only tells the engine which *installed* face to use.
The engine scripts store the Japanese face ``ＭＳ ゴシック``, which has no glyph
for 880 of the 4481 characters the game draws, so Windows substitutes a second
face per character and the strokes come out uneven.  The build renames that
literal to ``Glow Sans SC`` (12 ASCII bytes + a NUL pad - the same 13-byte slot,
so no offset in the file moves).  Two things have to be true for it to work:

* ``Glow Sans SC`` has to be installed as a family GDI can find.  Once per
  machine: ``python ..\\install_glow_sans.py --verify``.  It renames the Glow Sans
  SC Normal-Medium/Bold files into one family with a Regular and a Bold style -
  the stock names exist only as a typographic family, and GDI ignores those.
* build with ``--face "Glow Sans SC"``.  ``--face ""`` leaves the Japanese name
  in place.  The build warns when the named face is not installed, because GDI
  would otherwise substitute silently.

The exe's own default face table (used where a script names no face) is patched
separately, it is not part of the pack:

    python ..\\patch_yuris_charset.py --apply --fonts "Glow Sans SC,Microsoft YaHei,SimHei"

If the game already ran once, delete ``save\\config.sd`` (back it up first) - a
font chosen in 設定 → フォント一覧 sticks in there and overrides both of the
above.  The game resets volume and message speed with it.  Details:
glossary\\STYLE_GUIDE.md section 8.

The dialogue size
-----------------
``--td-size "M=32"`` sets how big the ADV dialogue is drawn.  ``M`` is the text
definition ``userdefine\\文字定義.txt`` commits, and its ``es.TD.SIZE.SET``
operands are single-byte integers, so writing them moves nothing in the file.
Menus, the speaker plate and the ruby definitions keep their own sizes; leave the
option off to keep the scripted 27 px.  The text area is 790x170 px with a line
pitch of size-2 and a fixed 480 px wrap, so 30..34 all fit 4 lines - 32 was
picked as the middle of that band.  The engine paginates instead of clipping, so
a bigger face only means more pages.  Details: glossary\\STYLE_GUIDE.md 8.6.

Building the pack
-----------------
    python build_cn_pack.py --workpack . --indir D:\\ysbin --face "Glow Sans SC" --td-size "M=32"
writes build\\update1.ypf plus the rebuilt scripts in build\\ysbin\\.

The build then checks itself before anything is installed: the pack must hold
exactly the rebuilt scripts, every string must decode back out of the packed
bytes with the Windows code page 936 table, and the branch/layout blocks must
still match the originals.  If any check fails the build stops and installs
nothing.  To repeat the check on its own:

    python verify_cn_pack.py build D:\\ysbin

Installing it into the game
---------------------------
    python build_cn_pack.py --workpack . --indir D:\\ysbin --install --install-dir "<game folder>"
copies update1.ypf to "<game folder>\\update1.ypf" and
"<game folder>\\pac\\update1.ypf".  The game prefers those over pac\\bn.ypf, and
the stock game ships neither, so deleting those two files undoes the patch
completely.  Close the game while copying - the packs are read at start-up only.
--install implies the self check above; add --no-verify only if you know why.
Add --face "Glow Sans SC" to apply the font rename (see The font above), and
--td-size "M=32" for the dialogue size (see The dialogue size above).
"""


def write_tsv(path: Path, header: tuple[str, ...],
              rows: list[tuple]) -> None:
    """Write a tab separated file; every field is known to hold no tab or CR."""
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\t'.join(header) + '\r\n')
        for row in rows:
            f.write('\t'.join(str(c) for c in row) + '\r\n')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Write a deduplicated translation work package.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python make_translation_workpack.py --indir D:\\ysbin '
               '--outdir workpack')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='folder holding ysc.ybn and the ystNNNNN.ybn scripts')
    ap.add_argument('--outdir', default='workpack',
                    help='folder to write the package into (default: ./workpack)')
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

    eargs = argparse.Namespace(indir=args.indir, repo=args.repo,
                               i_encoding=args.i_encoding, key=args.key,
                               verbose=args.verbose)
    ff, kcc, key, indir, files, paths = inj.load_game(eargs)
    print(f'key 0x{key:08X}, {len(files)} script(s) in {indir}')

    ids: dict[str, int] = {}
    counts: dict[str, int] = {}
    usages: list[tuple] = []
    scripts: list[tuple] = []
    nscripts = 0
    for p in files:
        try:
            recs = inj.word_records(p.read_bytes(), ff, key, kcc,
                                    args.i_encoding)
        except Exception as e:
            print(f'warning: skipping {p.name}: {type(e).__name__}: {e}',
                  file=sys.stderr)
            continue
        if not recs:
            continue
        nscripts += 1
        idx = inj.script_index(p.name)
        spath = inj.clean(paths.get(int(idx), '') if idx else '')
        scripts.append((idx, p.name, spath, len(recs)))
        for cmd_i, _j, lno, text in recs:
            text = inj.clean(text)          # no control bytes exist, this is a
            i = ids.get(text)               # no-op guard against a stray tab
            if i is None:
                i = ids[text] = len(ids) + 1
                counts[text] = 0
            counts[text] += 1
            usages.append((i, idx, p.name, cmd_i, lno, spath))

    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    lines = [(i, counts[t], len(t), t, '') for t, i in ids.items()]
    lines.sort()
    scripts.sort(key=lambda r: int(r[0]) if r[0] else -1)
    write_tsv(outdir / 'lines.tsv', LINES_HEADER, lines)
    write_tsv(outdir / 'usages.tsv', USAGES_HEADER, usages)
    write_tsv(outdir / 'scripts.tsv', SCRIPTS_HEADER, scripts)
    with open(outdir / 'README.txt', 'w', encoding='utf-8', newline='\n') as f:
        f.write(README)

    total = len(usages)
    distinct = len(lines)
    dup = total - distinct
    budget = sum(len(t) * n for t, n in counts.items())
    print(f'{nscripts} script(s) hold {total} line(s); {distinct} are distinct '
          f'({dup} repeated, {budget} characters in total)')
    for name in ('lines.tsv', 'usages.tsv', 'scripts.tsv', 'README.txt'):
        print(f'wrote {outdir / name}')
    print()
    print('fill the new_text column of lines.tsv, then build the game with')
    print(f'    python build_cn_pack.py --workpack {outdir} --face "Glow Sans SC" '
          f'--td-size "M=32"')
    print('lines left empty are filled with the original Japanese re-encoded '
          'to GBK, so a partly')
    print('translated build still shows readable text everywhere')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
