#!/usr/bin/env python
"""Merge per-scene Chinese translation files into ``workpack/lines.tsv``.

The translator edits one text file per scene under ``translation/userscript``
(``<scene>_中文.txt``, one line per line of the extracted scene text).  The
build, however, reads ``workpack/lines.tsv``: one row per *distinct* line,
keyed by ``id``.  This tool is the missing link between the two.

Alignment is positional and is verified, not assumed:

    translation/userscript/<scene>_中文.txt   line n
    yuris_text_out/text/.../userscript/<scene>.txt   line n   (same count)
    workpack/usages.tsv        row n of that script_idx       -> id
    workpack/lines.tsv         that id -> new_text

Before anything is written the tool checks that the Japanese text held in
``lines.tsv`` for those ids really is the scene text, line for line.  If it is
not, the scene is skipped and reported - the mapping is wrong and writing would
put Chinese dialogue on the wrong lines.

Because ``lines.tsv`` is keyed per distinct line, a line that occurs in two
scenes can only hold one translation.  Two different translations for the same
id are reported and the first scene (in ``scripts.tsv`` order) wins.

A line that is byte-identical to the Japanese source is written as an empty
``new_text``, i.e. "keep this line Japanese" - that is the state the build
already understands.

Default is a dry run.  ``--apply`` rewrites ``workpack/lines.tsv`` (leaving
``lines.tsv.bak``) and ``--out PATH`` writes a copy instead.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from check_glossary import LINES_HEADER, SUBSTITUTIONS, unencodable

ROOT = Path(__file__).resolve().parent
SUFFIX = '_\u4e2d\u6587.txt'                    # "_中文.txt"
SCENE_TEXT = ROOT / 'yuris_text_out' / 'text' / 'data' / 'script' / 'userscript'
TRANSLATION_DIR = ROOT / 'translation' / 'userscript'


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.warnings = 0

    def error(self, where: str, msg: str) -> None:
        self.errors += 1
        print(f'[error] {where}: {msg}')

    def warn(self, where: str, msg: str) -> None:
        self.warnings += 1
        print(f'[warn ] {where}: {msg}')

    def note(self, msg: str) -> None:
        print(f'[info ] {msg}')


def read_tsv(path: Path) -> list[list[str]]:
    with path.open(encoding='utf-8-sig', newline='') as fh:
        return [row for row in csv.reader(fh, delimiter='\t')]


def load_scene_order(workpack: Path) -> dict[int, str]:
    """``script_idx -> scene file name`` from scripts.tsv, in file order."""
    with (workpack / 'scripts.tsv').open(encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh, delimiter='\t'))
    return {int(r['script_idx']): r['script_path'].rsplit('\\', 1)[-1] for r in rows}


def load_usages(workpack: Path, idx: int) -> list[int]:
    """Row ids of one script, in game order."""
    with (workpack / 'usages.tsv').open(encoding='utf-8-sig', newline='') as fh:
        return [int(r['id']) for r in csv.DictReader(fh, delimiter='\t')
                if int(r['script_idx']) == idx]


def read_translation(path: Path) -> list[str]:
    raw = path.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    return raw.decode('utf-8').splitlines()


def merge(workpack: Path, translation_dir: Path, only: list[str],
          report: Report) -> tuple[list[list[str]], dict[str, tuple[int, int, int]]]:
    """Return the updated lines.tsv rows plus per-scene counters."""
    rows = read_tsv(workpack / 'lines.tsv')
    if tuple(rows[0]) != LINES_HEADER:
        report.error(str(workpack / 'lines.tsv'), f'header is {rows[0]}, '
                     f'expected {list(LINES_HEADER)}')
        return rows, {}
    orig_col = LINES_HEADER.index('orig_text')
    new_col = LINES_HEADER.index('new_text')
    by_id = {int(r[0]): r for r in rows[1:]}

    order = load_scene_order(workpack)
    stats: dict[str, int] = {}
    seen: dict[int, tuple[str, str]] = {}        # id -> (scene, translation)
    conflicts: dict[int, list[tuple[str, str]]] = {}

    for idx, scene in sorted(order.items()):
        src = SCENE_TEXT / scene
        dst = translation_dir / (scene[:-4] + SUFFIX)
        if only and not any(s in scene for s in only):
            continue
        if not dst.is_file():
            continue
        if not src.is_file():
            report.error(dst.name, f'the scene source {src} is missing')
            continue

        ids = load_usages(workpack, idx)
        jp = src.read_text(encoding='utf-8').splitlines()
        cn = read_translation(dst)

        if len(ids) != len(jp) or len(cn) != len(jp):
            report.error(dst.name, f'{len(jp)} source line(s) and {len(cn)} '
                         f'translated line(s), but usages.tsv has {len(ids)} row(s) '
                         f'for script_idx {idx} - not merged')
            continue

        mismatched = [i for i, (a, b) in enumerate(zip(jp, cn))
                      if by_id[ids[i]][orig_col] != a]
        if mismatched:
            i = mismatched[0]
            report.error(dst.name, f'{len(mismatched)} line(s) do not match the '
                         f'Japanese text in lines.tsv (first at line {i + 1}, '
                         f'id {ids[i]}) - the mapping is wrong, not merged')
            continue

        covered = set(ids)
        for i in covered:                        # covered by a merged scene
            seen.setdefault(i, None)

        filled = kept = dropped = 0
        for i, text in enumerate(cn):
            row = by_id[ids[i]]
            if not text.strip():
                report.warn(f'{dst.name}:{i + 1}', 'the line is empty - it will '
                            'keep the Japanese text')
                kept += 1
                continue
            if '\t' in text:
                report.error(f'{dst.name}:{i + 1}', 'the line holds a tab, which '
                             'would break the work package columns')
                continue
            bad = unencodable(text, allowed=''.join(SUBSTITUTIONS))
            if bad:
                report.error(f'{dst.name}:{i + 1}', f'the line holds U+{ord(bad):04X} '
                             f'{bad!r}, which code page 936 can not show')
                continue
            if text == row[orig_col]:
                text = ''                        # left in Japanese on purpose
            if not text:
                kept += 1
                continue
            filled += 1
            current = seen.get(ids[i])
            if current is None:
                if row[new_col]:
                    dropped += 1
                seen[ids[i]] = (scene, text)
                row[new_col] = text
            elif current[1] != text:
                conflicts.setdefault(ids[i], [current]).append((scene, text))
        stats[dst.name] = (filled, kept, dropped)
        report.note(f'{dst.name}: {filled} line(s) translated, {kept} kept in '
                    f'Japanese' + (f', {dropped} overwrote an earlier merge'
                                   if dropped else ''))

    for i, entries in sorted(conflicts.items()):
        report.warn(f'id {i}', 'this line is translated differently in more than '
                    'one scene; the first one wins: '
                    + ' | '.join(f'{s}: {t!r}' for s, t in entries))

    return rows, stats


def write_lines(path: Path, rows: list[list[str]], backup: bool) -> None:
    if backup and path.is_file():
        path.with_suffix(path.suffix + '.bak').write_bytes(path.read_bytes())
    buf = ['\t'.join(r) for r in rows]
    path.write_bytes(('\ufeff' + '\r\n'.join(buf) + '\r\n').encode('utf-8'))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description='Merge translation/userscript/*_中文.txt into '
                    'workpack/lines.tsv.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('--workpack', default=str(ROOT / 'workpack'),
                    help='work package directory')
    ap.add_argument('--translation-dir', default=str(TRANSLATION_DIR),
                    help='directory holding the per-scene translations')
    ap.add_argument('--only', nargs='+', metavar='SUBSTRING',
                    help='merge only the scenes whose name holds this substring')
    ap.add_argument('--out', help='write the merged table here instead of reporting')
    ap.add_argument('--apply', action='store_true',
                    help='rewrite lines.tsv in place (leaves lines.tsv.bak)')
    ap.add_argument('--force', action='store_true',
                    help='write even when a scene or a line had to be skipped')
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workpack = Path(args.workpack).expanduser()
    report = Report()
    rows, stats = merge(workpack, Path(args.translation_dir).expanduser(),
                        args.only or [], report)

    total = sum(1 for r in rows[1:] if r[LINES_HEADER.index('new_text')])
    report.note(f'{len(rows) - 1} row(s), {total} with a translation')

    if report.errors and not args.force:
        print(f'{report.errors} error(s), {report.warnings} warning(s) - '
              'nothing written', file=sys.stderr)
        return 1
    if args.force and (report.errors or report.warnings):
        report.note(f'--force: writing anyway with {report.errors} error(s) and '
                    f'{report.warnings} warning(s); the affected scene(s) and '
                    'line(s) are NOT in the result')
    if args.apply:
        write_lines(workpack / 'lines.tsv', rows, backup=True)
        report.note(f'wrote {workpack / "lines.tsv"} '
                    f'(previous file kept as lines.tsv.bak)')
    elif args.out:
        write_lines(Path(args.out).expanduser(), rows, backup=False)
        report.note(f'wrote {args.out}')
    else:
        report.note('dry run, nothing written. Add --apply, or --out PATH.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
