"""Collect terminology candidates out of the extracted game text.

Reads the per-scene text dumps produced by ``extract_yuris_text.py``
(default: ``yuris_text_out\\text\\data\\script\\userscript\\*.txt``, one
displayed string per line, dialogue lines written as ``<name>「<text>」``)
and reports every kind of term a translation has to keep consistent:

  ruby      ``<<base/reading>>`` pairs - the author's own glossary.  Each
            pair says "this word is a proper noun or a technical term",
            and the reading is the pronunciation to look the word up by.
  speaker   the ``<name>「`` prefix of a dialogue line: the cast list,
            including role-only labels such as ``young detective``.
  kana      katakana words (foreign loans, onomatopoeia, names).
  kanji     repeated kanji compounds - place names, organisations, titles.
  latin     ASCII words and initialisms.

Every row carries the number of occurrences and the scenes it appears in,
so a translator can see which terms matter before touching the text, and
``--workpack`` can be used instead to read ``workpack\\lines.tsv`` (the
count there is the number of *distinct* lines, not occurrences).

Usage
-----
    python extract_terms.py                      # -> glossary\\candidates_*.tsv
    python extract_terms.py --min-count 3
    python extract_terms.py --workpack workpack --outdir glossary
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_TEXT_DIR = Path('yuris_text_out') / 'text' / 'data' / 'script' / 'userscript'
DEFAULT_OUT_DIR = Path('glossary')

RUBY_RE = re.compile(r'≪([^≪≫／]{1,16})／([^≪≫]{1,24})≫')
SPEAKER_RE = re.compile(r'^([^\s「『（(]{1,10})[「『]')
KANA_RE = re.compile(r'[ァ-ヴヷ-ヺー]{2,}')
KANJI_RE = re.compile(r'[一-鿿々]{2,6}')
LATIN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]{2,}")

# dialogue-line noise that is not a character name
ROLE_RE = re.compile(r'(刑事|男|女|声|兵|人々|たち|者)$')


class Bag:
    """Term -> (occurrences, scenes it was seen in)."""

    def __init__(self) -> None:
        self.hits: dict[str, int] = defaultdict(int)
        self.readings: dict[str, str] = {}
        self.scenes: dict[str, set[str]] = defaultdict(set)

    def add(self, term: str, scene: str, reading: str | None = None,
            n: int = 1) -> None:
        self.hits[term] += n
        self.scenes[term].add(scene)
        if reading and not self.readings.get(term):
            self.readings[term] = reading

    def rows(self, min_count: int) -> list[tuple[str, str, int, str]]:
        out = [(t, self.readings.get(t, ''), n, '|'.join(sorted(self.scenes[t])))
               for t, n in self.hits.items() if n >= min_count]
        out.sort(key=lambda r: (-r[2], r[0]))
        return out


def scan_text_dir(indir: Path) -> dict[str, Bag]:
    bags = {k: Bag() for k in ('ruby', 'speaker', 'kana', 'kanji', 'latin')}
    files = sorted(indir.glob('*.txt'))
    if not files:
        raise SystemExit(f'no *.txt under {indir}')
    for path in files:
        scene = path.stem
        for text in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if not text.strip():
                continue
            for base, reading in RUBY_RE.findall(text):
                bags['ruby'].add(base, scene, reading)
            m = SPEAKER_RE.match(text)
            if m:
                name = m.group(1)
                bags['speaker'].add(name, scene,
                                    'role label' if ROLE_RE.search(name) else None)
            body = RUBY_RE.sub(r'\1', text)
            for word in KANA_RE.findall(body):
                bags['kana'].add(word, scene)
            for word in KANJI_RE.findall(body):
                bags['kanji'].add(word, scene)
            for word in LATIN_RE.findall(body):
                bags['latin'].add(word.lower(), scene)
    return bags


def scan_workpack(wp: Path) -> dict[str, Bag]:
    lines = wp / 'lines.tsv'
    if not lines.exists():
        raise SystemExit(f'{lines} not found')
    bags = {k: Bag() for k in ('ruby', 'speaker', 'kana', 'kanji', 'latin')}
    with lines.open(encoding='utf-8') as fp:
        header = fp.readline().rstrip('\n').split('\t')
        try:
            i_orig, i_chars = header.index('orig_text'), header.index('chars')
        except ValueError:
            raise SystemExit('lines.tsv has no orig_text/chars column')
        for row in fp:
            cells = row.rstrip('\n').split('\t')
            if len(cells) <= i_orig:
                continue
            text = cells[i_orig]
            weight = max(1, int(cells[i_chars] or 1))
            for base, reading in RUBY_RE.findall(text):
                bags['ruby'].add(base, 'workpack', reading, weight)
            m = SPEAKER_RE.match(text)
            if m:
                bags['speaker'].add(m.group(1), 'workpack', None, weight)
            body = RUBY_RE.sub(r'\1', text)
            for word in KANA_RE.findall(body):
                bags['kana'].add(word, 'workpack', None, weight)
            for word in KANJI_RE.findall(body):
                bags['kanji'].add(word, 'workpack', None, weight)
            for word in LATIN_RE.findall(body):
                bags['latin'].add(word.lower(), 'workpack', None, weight)
    return bags


def write(path: Path, rows: list[tuple[str, str, int, str]], header: str) -> None:
    path.write_text(header + '\n' + ''.join('\t'.join(str(c) for c in r) + '\n'
                                            for r in rows), encoding='utf-8')
    print(f'{path}  ({len(rows)} row(s))')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--indir', default=str(DEFAULT_TEXT_DIR),
                    help='per-scene text dump directory')
    ap.add_argument('--workpack', default=None,
                    help='read <dir>\\lines.tsv instead of the text dumps')
    ap.add_argument('--outdir', default=str(DEFAULT_OUT_DIR))
    ap.add_argument('--min-count', type=int, default=2,
                    help='drop kana/kanji/latin candidates seen fewer times '
                         '(ruby and speakers are always kept)')
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bags = (scan_workpack(Path(args.workpack)) if args.workpack
            else scan_text_dir(Path(args.indir)))
    k = args.min_count
    write(outdir / 'candidates_ruby.tsv', bags['ruby'].rows(1),
          'base\treading\tcount\tscenes')
    write(outdir / 'candidates_speaker.tsv', bags['speaker'].rows(1),
          'name\tnote\tcount\tscenes')
    write(outdir / 'candidates_kana.tsv', bags['kana'].rows(max(2, k)),
          'term\treading\tcount\tscenes')
    write(outdir / 'candidates_kanji.tsv', bags['kanji'].rows(k),
          'term\treading\tcount\tscenes')
    write(outdir / 'candidates_latin.tsv', bags['latin'].rows(max(2, k)),
          'term\treading\tcount\tscenes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
