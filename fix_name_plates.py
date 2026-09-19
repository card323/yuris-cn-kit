#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Put every speaker prefix into the exact form the engine cuts.

Why this exists
---------------
A speaker name is not a separate field: it is the head of the dialogue line.
``es.CHAR.NAME.SEARCH`` (``es_charname.yst:60-103``) only recognises a name when
the line starts with ``name + mark``, where *mark* is one of the three strings
registered in ``userdefine\\キャラ名定義.txt:14-16``:

    「      『      （

On a match the engine cuts the name off, paints it on the name plate and leaves
the rest in the dialogue box.  On a miss nothing is cut: the plate stays empty
and the whole ``name + text`` is drawn inside the dialogue box.

So a line has to look like ``吐月「…」``, ``珠夜『…』`` or ``文鳴（…）`` - the mark
comes from the original, not from taste.  A line written as ``吐月“…”`` is *not*
recognised, because the curly quote is not a registered mark, and renders as if
the layout were broken.  See ``glossary\\STYLE_GUIDE.md`` §3.

What this tool does
-------------------
For every line whose Japanese original carries a plate, the translation must
start with the registered name followed by the registered mark:

* prefix already right, only the quote differs  ->  the quote takes the mark
* prefix translated (``文鳴`` -> ``文鸣``)      ->  the prefix goes back to the
  registered Japanese name taken from the aligned original line

The closing mark follows the opener.  Nothing else is touched: inner quotes,
ruby, wording and punctuation stay exactly as written.

A line whose translation *adds* a name that the original did not have is only
reported, because whether the plate belongs there is a translation decision.

Default is a dry run.  ``--apply`` rewrites the per-scene files in place,
keeping a ``.bak`` copy of each one it changes.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from check_glossary import (Report, find_names_file, load_names, plate)

ROOT = Path(__file__).resolve().parent
SUFFIX = '_\u4e2d\u6587.txt'                     # "_中文.txt"
SCENE_TEXT = ROOT / 'yuris_text_out' / 'text' / 'data' / 'script' / 'userscript'
TRANSLATION_DIR = ROOT / 'translation' / 'userscript'

OPENERS = '\u300c\u300e\uff08\u201c\u2018'        # 「 『 （ “ ‘
QUOTE_OPENERS = '\u201c\u2018'                    # “ ‘ - never a plate mark
CLOSERS = {'\u300c': '\u300d', '\u300e': '\u300f', '\uff08': '\uff09',
           '\u201c': '\u201d', '\u2018': '\u2019'}
DEFAULT_MARK = '\u300c'                           # 「


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    return raw.decode('utf-8')


def write_text(path: Path, text: str) -> None:
    path.write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n')
                     .encode('utf-8'))


def first_opener(text: str) -> int:
    for i, ch in enumerate(text):
        if ch in OPENERS:
            return i
    return -1


def normalize(cn: str, name: str, mark: str,
              names: set[str]) -> tuple[str, str, str]:
    """Return ``(text, kind, head)`` for one translated line.

    *name* and *mark* are what the engine cuts out of the Japanese original, or
    ``('', '')`` when it cuts nothing there.  *kind* is ``''`` when the line is
    left alone, ``'quote'`` when only the quotation marks had to change,
    ``'prefix'`` when the head was replaced by the registered name and
    ``'added'`` when the line puts a name in front of speech that the original
    narrated.  *head* is whatever stood in front of the quote.
    """
    if not cn:
        return cn, '', ''
    if not name:
        # No plate in the original: only ever a name the translation added.
        i = first_opener(cn)
        if i <= 0 or cn[i] not in QUOTE_OPENERS or cn[:i] not in names:
            return cn, '', ''
        head, rest = cn[:i], cn[i + 1:]
        j = rest.find(CLOSERS[cn[i]])
        if j < 0:
            return cn, '', ''
        # The name becomes the plate, so the quote pair has to move inside it.
        return (head + DEFAULT_MARK + rest[:j] + CLOSERS[DEFAULT_MARK]
                + rest[j + 1:], 'added', head)

    if cn.startswith(name + mark):
        return cn, '', name
    i = first_opener(cn)
    if i < 0:
        return cn, '', ''
    head, rest = cn[:i], cn[i + 1:]
    text = name + mark + rest
    # The closing mark has to follow the opening one, so a curly close left over
    # from the translation's own quoting becomes the mark's own closer.
    if text[-1] in '\u201d\u2019' and text[-1] != CLOSERS[mark]:
        text = text[:-1] + CLOSERS[mark]
    return text, ('quote' if head == name else 'prefix'), head


def run(translation_dir: Path, scene_dir: Path, names: set[str], only: list[str],
        apply_changes: bool, report: Report) -> int:
    pairs = []
    for dst in sorted(translation_dir.glob('*' + SUFFIX)):
        scene = dst.name[:-len(SUFFIX)] + '.txt'
        src = scene_dir / scene
        if only and not any(s in scene for s in only):
            continue
        if not src.is_file():
            report.error(dst.name, f'no scene source at {src}')
            continue
        pairs.append((dst, src))

    if not pairs:
        report.error(str(translation_dir), 'no per-scene translation was found')
        return 1

    kinds = {'quote': 0, 'prefix': 0, 'added': 0}
    heads: dict[tuple[str, str], int] = collections.Counter()
    changed_files = 0
    unusual = 0
    unbalanced = 0

    for dst, src in pairs:
        cn_lines = read_text(dst).splitlines()
        jp_lines = read_text(src).splitlines()
        if len(cn_lines) != len(jp_lines):
            report.error(dst.name, f'{len(jp_lines)} source line(s) but '
                         f'{len(cn_lines)} translated line(s) - not touched')
            continue

        out, edits = [], 0
        for n, (jp, cn) in enumerate(zip(jp_lines, cn_lines), 1):
            name, mark = plate(jp, names)
            if cn.count('\u300c') != cn.count('\u300d') or \
                    cn.count('\u201c') != cn.count('\u201d') or \
                    cn.count('\u2018') != cn.count('\u2019'):
                unbalanced += 1
                report.warn(f'{dst.name}:{n}', 'the quotation marks are not '
                            'balanced on this line')
            if not name and not cn:
                out.append(cn)
                continue
            if name and cn and first_opener(cn) < 0:
                unusual += 1
                report.warn(f'{dst.name}:{n}', f'the original has the plate '
                            f'{name + mark!r} but the translation holds no '
                            'quotation mark - left alone')
                out.append(cn)
                continue
            text, kind, head = normalize(cn, name, mark, names)
            if kind == 'added':
                report.warn(f'{dst.name}:{n}', f'the original line has no plate, '
                            f'but this translation puts {head!r} in front of the '
                            'speech - it becomes the plate and the quote pair '
                            'moves after it')
            if kind:
                kinds[kind] += 1
                heads[(name + mark, head)] += 1
                if text != cn:
                    edits += 1
            out.append(text)

        if edits:
            changed_files += 1
            report.note(f'{dst.name}: {edits} line(s) to rewrite')
            if apply_changes:
                backup = dst.with_suffix(dst.suffix + '.bak')
                if not backup.exists():
                    backup.write_bytes(dst.read_bytes())
                write_text(dst, '\n'.join(out))

    report.note(f'{len(pairs)} scene file(s) read, '
                f'{kinds["quote"]} line(s) only needed the quote fixed, '
                f'{kinds["prefix"]} line(s) had a translated prefix, '
                f'{kinds["added"]} line(s) added a plate')
    if kinds['added']:
        report.note(f'{kinds["added"]} line(s) put a registered name in front of '
                    'speech the original narrated - check those by hand')
    if unbalanced:
        report.note(f'{unbalanced} line(s) with unbalanced quotes (reported once '
                    'per line)')

    if heads:
        report.note('prefixes that were replaced (registered name <- what was written):')
        width = max(len(head) for _key, head in heads)
        for (key, head), n in sorted(heads.items(), key=lambda kv: -kv[1]):
            if key and key != head:
                print(f'          {key:<6} <- {head:<{width}}  x{n}')
            elif not key:
                print(f'          (plate the original did not have) {head}  x{n}')

    if not apply_changes:
        report.note(f'{changed_files} file(s) would change; dry run, nothing '
                    'written. Add --apply to rewrite them.')
    elif changed_files:
        report.note(f'{changed_files} file(s) rewritten (previous copies kept '
                    'as .bak)')
    else:
        report.note('every file already matches the rule - nothing to write')
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description='Rewrite speaker prefixes/quotes into the form the engine '
                    'cuts (see glossary/STYLE_GUIDE.md section 3).',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('--translation-dir', default=str(TRANSLATION_DIR),
                    help='directory holding the per-scene translations')
    ap.add_argument('--scene-dir', default=str(SCENE_TEXT),
                    help='directory holding the extracted Japanese scenes')
    ap.add_argument('--names', help='the character name script to read')
    ap.add_argument('--only', nargs='+', metavar='SUBSTRING',
                    help='only the scenes whose name holds this substring')
    ap.add_argument('--apply', action='store_true',
                    help='rewrite the files (keeps a .bak of each one changed)')
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = Report()
    names_file = Path(args.names) if args.names else find_names_file(ROOT)
    names = load_names(names_file, report)
    if not names:
        print('error: no registered character names - nothing can be checked',
              file=sys.stderr)
        return 1
    rc = run(Path(args.translation_dir).expanduser(),
             Path(args.scene_dir).expanduser(), names, args.only or [],
             args.apply, report)
    if report.errors:
        print(f'{report.errors} error(s), {report.warnings} warning(s)',
              file=sys.stderr)
        return 1
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
