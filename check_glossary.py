#!/usr/bin/env python
"""Check the Chinese termbase and the filled-in translation work package.

Two independent passes, both optional:

``glossary`` pass (default: ``glossary/glossary.tsv``)
    schema, duplicate terms, and - most importantly - that every Chinese
    rendering survives the build's code page.  The engine renders text through
    GDI with ``lfCharSet`` = 936, so anything outside cp936 is dropped at build
    time; catching it here is much cheaper than reading it out of the build log.

``--lines`` pass (usually ``workpack/lines.tsv``)
    the checks that only make sense once a translation exists:

    * every filled ``new_text`` is cp936 encodable
    * ruby markup survives the engine's parser (``es.TX.RUBY.CHK``): balanced
      ``《`` ``》``, exactly one ``／`` per span, and the author's emphasis spans
      kept to a single character.  ``《``/``》`` are engine syntax - a prose
      ``《title》`` stops the game - so titles are written as ``〈title〉``
    * no character the engine reads as a control code slips in
      (``es.TX.CRPREPLACE`` turns the byte pairs of ``CONTROL_CHARS`` into the
      draw markers ``R``/``P``/``C`` and deletes the character from the line), and
      no ``／`` outside a ruby span, which is where the name window cuts a name
      plate out of the text
    * a speaker line keeps its ``<name>「body」`` shape, because the engine
      matches the literal's prefix against the names registered in
      ``es.CHAR.NAME`` (``キャラ名定義.txt``) and only then cuts the name out of
      the body - rename the prefix and the name is drawn inside the text box
    * the translation is not wildly longer than the original (the dialogue box
      has a fixed wrap width - the message control's 790 px minus 40 px)
    * glossary terms that occur in the original occur as their agreed Chinese
      form in the translation

Rows with an empty ``new_text`` are skipped by the ``--lines`` pass: an empty
cell means "keep this line in Japanese" and is a valid state.

Exit code is 0 with warnings, 1 when the result would not build or would render
wrongly, 2 for usage or I/O trouble.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------- #
# constants shared with the build
# --------------------------------------------------------------------------- #

GLOSSARY_HEADER = ('cat', 'orig', 'reading', 'cn', 'note', 'count')
GLOSSARY_CATS = ('name', 'place', 'org', 'skill', 'deity', 'item', 'term',
                 'gikun', 'register', 'h', 'other')
LINES_HEADER = ('id', 'count', 'chars', 'orig_text', 'new_text')
# categories whose Chinese form has to be used consistently in the script
TERM_CATS = ('place', 'org', 'skill', 'deity', 'item', 'term')

# The four characters cp936 can not hold.  build_cn_pack.py swaps them instead
# of refusing the line, so they are reported but never fatal in new_text.
SUBSTITUTIONS = {'\u226a': '\u300a', '\u226b': '\u300b',
                 '\u30fb': '\u00b7', '\u266a': '\u3002'}
CODE_PAGE = 'cp936'

# Ruby markup is ≪base／reading≫, with ・ as the per-character emphasis reading.
# The delimiters are data, not syntax the engine hard codes: メイン定義.txt sets
# $gStr1145(36,25..27) = ≪ ／ ≫ and es_text.yst reads them back at boot.  ≪ and ≫
# have no cp936 mapping, so the build's substitution table turns them into 《 and
# 》 - which means the engine parses 《 ／ 》.  Those two characters are therefore
# *syntax*: a prose 《title》 reaches es.TX.RUBY.CHK as ruby markup with no
# reading, and the game stops with ルビ記述エラーです。.  Titles use 〈 〉 (cp936
# a1b4/a1b5, not a delimiter) instead.
RUBY_OPEN, RUBY_CLOSE, RUBY_SEP = '\u300a', '\u300b', '\uff0f'
RUBY_SPAN_RE = re.compile(r'\u300a([^\u300a\u300b]*)\u300b')
RUBY_ALL = (RUBY_OPEN, RUBY_CLOSE, RUBY_SEP, '\u226a', '\u226b')
TITLE_OPEN, TITLE_CLOSE = '\u3008', '\u3009'
EMPHASIS = '\u00b7'                 # ・ as the engine sees it, after substitution
MAX_RUBY_SPANS = 64                 # engine limit per line

# ``es.TX.CRPREPLACE`` (``es_text.yst``:991-1075) is the second place the renderer
# reads the *text* as syntax rather than prose.  For every full-width character it
# compares the two bytes against three pairs and, on a match, rewrites the
# structure marker to ``R``/``P``/``C`` and deletes the character from the drawn
# string (``_strdel($sStr3805, i, 1)``).  Shift-JIS leaves those pairs unassigned,
# so the Japanese original can never hold one; cp936 spells four real characters
# with them, and two of those are words a translator has every reason to type
# (镳 in 分道扬镳, 矬 in 矬子).  The line then renders, quietly one character short.
#   key: character -> (cp936 bytes, what the engine does with it, fatal?)
CONTROL_CHARS: dict[str, tuple[str, str, bool]] = {
    '\u9573': ('EF F0', 'the character is deleted from the drawn line, which logs '
                        'an empty "R" entry in its place', True),
    '\u953a': ('EF F1', 'this engine never reads that pair, so the character is '
                        'drawn - but the pair is reserved for engine codes', False),
    '\u77e7': ('EF F2', 'the character is deleted and the line breaks to a new '
                        'page', True),
    '\u77ec': ('EF F3', 'the character is deleted and the line stops for a click '
                        'wait', True),
}

# glyphs that must not survive into Chinese prose
KANA_RE = re.compile(r'[\u3041-\u3096\u30a1-\u30fa]')
JAPANESE_ONLY = {'\u3005': '\u3005', '\u30fc': '\u30fc', '\u30f6': '\u30f6'}

# engine metrics (文字定義.txt / es_text.yst): dialogue advances 30 px per full
# width character and draws the glyphs 38 px tall; the wrap limit is the message
# control's width - 40 px = 750 px (advance + 2 px margin + a 2 character
# kinsoku lookahead), the 480 px in es_text.yst:2041 is a vertical page budget.
DIALOGUE_PX = 30
WRAP_PX = 750
FULLWIDTH_PX = 30.0
NARROW_PX = 15.0

NAME_REGISTRATION_RE = re.compile(
    r'GOSUB\[#="es\.CHAR\.NAME"\s+PSTR="([^"]*)"')
# The marks registered through es.CHAR.NAME.MARK.SET in キャラ名定義.txt.  A name
# is only cut off a line when it is immediately followed by one of these, so the
# set is part of the engine contract, not a typographic choice.
PLATE_MARKS = '\u300c\u300e\uff08'          # 「 『 （
DEFAULT_NAME_SOURCES = (
    'yuris_text_out/decompiled/data/script/userdefine/\u30ad\u30e3\u30e9\u540d\u5b9a\u7fa9.txt',
    'yuris_text_out/text/data/script/userdefine/\u30ad\u30e3\u30e9\u540d\u5b9a\u7fa9.txt',
)


class Report:
    """Collects errors and warnings so the run can report everything at once."""

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


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def unencodable(text: str, allowed: str = '') -> str:
    """Return the first character cp936 can not encode, else ``''``.

    Characters named in *allowed* are skipped: the build substitutes them
    instead of refusing the line, so they are only reported as warnings.
    """
    for ch in text:
        if ch in allowed:
            continue
        try:
            ch.encode(CODE_PAGE)
        except UnicodeEncodeError:
            return ch
    return ''


def substitute(text: str) -> str:
    """Return *text* as the build ships it (``SUBSTITUTIONS`` applied).

    Mirrors ``transcode_yuris_gbk.substitute``: this is the text the engine
    parses, so every ruby check runs on the substituted form.
    """
    for src, dst in SUBSTITUTIONS.items():
        text = text.replace(src, dst)
    return text


def control_hits(text: str) -> list[tuple[str, str, str, bool]]:
    """Return ``(char, cp936 bytes, effect, fatal)`` for every control character.

    See :data:`CONTROL_CHARS`: these are the characters ``es.TX.CRPREPLACE``
    silently turns into draw markers instead of glyphs.  Works on the text the
    engine parses, so pass the raw (unsubstituted) Chinese.
    """
    return [(ch, *CONTROL_CHARS[ch]) for ch in text if ch in CONTROL_CHARS]


def display_px(text: str) -> float:
    """Rough rendered width in pixels, counting each character by its type.

    Ruby markup is stripped, keeping only the base, because that is what the
    dialogue box measures.
    """
    visible = RUBY_SPAN_RE.sub(lambda m: m.group(1).split(RUBY_SEP)[0],
                               substitute(text))
    total = 0.0
    for ch in visible:
        total += NARROW_PX if unicodedata.east_asian_width(ch) in 'NaH' else FULLWIDTH_PX
    return total


def ruby_spans(text: str) -> list[tuple[str, str]]:
    """Return the ``(base, reading)`` pairs of a line, as the engine sees them."""
    out = []
    for m in RUBY_SPAN_RE.finditer(substitute(text)):
        body = m.group(1)
        base, _, reading = body.partition(RUBY_SEP)
        out.append((base, reading))
    return out


def ruby_errors(text: str) -> list[str]:
    """Replay the engine's ruby parser and return what it would stop on.

    This is a port of ``es.TX.RUBY.CHK`` in ``data/script/eris/es_text.yst``,
    which walks the line a character at a time through three states::

        text -《- base -／- reading -》- text

    and calls ``es._mes`` with ``ルビ記述エラーです。`` - an OK-only dialog that
    ends the game - on every deviation.  *text* must be the substituted form,
    i.e. what :func:`substitute` returns, because that is what the engine sees.

    The engine stops at the *first* deviation (the handler is followed by
    ``END[]``), so at most one message is returned.

    Structural problems only; an empty base, an empty reading and the emphasis
    span width are per-span details, reported by :func:`check_ruby`.
    """
    def stop(what: str) -> list[str]:
        return [f'{what} - the engine stops with ルビ記述エラーです。']

    state = 0
    base = reading = ''
    for ch in text:
        if state == 0:
            if ch == RUBY_OPEN:
                state, base = 1, ''
            elif ch == RUBY_CLOSE:
                return stop(f'{RUBY_CLOSE} closes a ruby span that was never '
                            f'opened with {RUBY_OPEN}')
        elif state == 1:
            if ch == RUBY_SEP:
                state, reading = 2, ''
            elif ch == RUBY_OPEN:
                return stop(f'{RUBY_OPEN} opens a ruby span inside '
                            f'{RUBY_OPEN}{base}')
            elif ch == RUBY_CLOSE:
                return stop(f'{RUBY_OPEN}{base}{RUBY_CLOSE} holds no '
                            f'{RUBY_SEP}, so the engine reads it as ruby with an '
                            f'empty reading; {RUBY_OPEN}/{RUBY_CLOSE} are its ruby '
                            f'delimiters, a title is written '
                            f'{TITLE_OPEN}title{TITLE_CLOSE}')
            else:
                base += ch
        else:
            if ch == RUBY_CLOSE:
                state = 0
            elif ch == RUBY_OPEN:
                return stop(f'{RUBY_OPEN} opens a ruby span inside '
                            f'{RUBY_OPEN}{base}{RUBY_SEP}{reading}')
            else:
                reading += ch
    if state == 1:
        return stop(f'{RUBY_OPEN}{base} is never closed')
    if state == 2:
        return stop(f'{RUBY_OPEN}{base}{RUBY_SEP}{reading} is never closed')
    return []


def plate(text: str, names: set[str]) -> tuple[str, str]:
    """Return ``(name, mark)`` when the engine cuts a name off *text*.

    ``es.CHAR.NAME.SEARCH`` cuts only when the line starts with a registered
    name that is immediately followed by one of the marks registered through
    ``es.CHAR.NAME.MARK.SET`` - ``「``, ``『`` and ``（`` in this game.  That is
    the whole test, so a line whose head is anything else keeps an empty name
    plate and has the name painted inside the dialogue box.  The longest match
    wins, which is what the shipped scripts rely on (``\u75371`` before ``\u7537``).
    """
    best = ('', '')
    for name in names:
        if len(name) < len(text) and text.startswith(name) \
                and text[len(name)] in PLATE_MARKS \
                and len(name) > len(best[0]):
            best = (name, text[len(name)])
    return best


def load_names(path: Path | None, report: Report) -> set[str]:
    """The names registered through ``es.CHAR.NAME``, i.e. valid prefixes."""
    if path is None:
        report.note('no character-name script found - the speaker-prefix check '
                    'is skipped (pass --names <character name script>)')
        return set()
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    names = {m.group(1) for m in NAME_REGISTRATION_RE.finditer(text)}
    if not names:
        report.warn(str(path), 'no es.CHAR.NAME registrations found')
    else:
        report.note(f'{len(names)} registered character names from {path.name}')
    return names


def read_tsv(path: Path, header: tuple[str, ...], report: Report
             ) -> list[tuple[int, list[str]]]:
    """Read a TSV, skipping blank lines and ``#`` comments."""
    rows: list[tuple[int, list[str]]] = []
    with io.open(path, encoding='utf-8-sig', newline='') as fp:
        first = True
        for lineno, raw in enumerate(fp, 1):
            line = raw.rstrip('\r\n')
            if not line or line.startswith('#'):
                continue
            if first:
                first = False
                got = line.split('\t')
                if tuple(got) != header:
                    report.error(f'{path}:{lineno}',
                                 f'header is {got}, expected {list(header)}')
                    return []
                continue
            rows.append((lineno, line.split('\t')))
    return rows


# --------------------------------------------------------------------------- #
# glossary pass
# --------------------------------------------------------------------------- #

def check_glossary(path: Path, report: Report) -> dict[str, list[tuple[str, str]]]:
    """Validate the termbase; return ``{cat: [(orig, cn), ...]}`` for the
    spelling-consistency check over the translated lines."""
    rows = read_tsv(path, GLOSSARY_HEADER, report)
    report.note(f'{len(rows)} glossary entries in {path}')
    seen: dict[str, int] = {}
    terms: dict[str, list[tuple[str, str]]] = {}

    for lineno, cols in rows:
        where = f'{path.name}:{lineno}'
        if len(cols) != len(GLOSSARY_HEADER):
            report.error(where, f'{len(cols)} column(s), expected '
                                f'{len(GLOSSARY_HEADER)} (tab separated)')
            continue
        cat, orig, reading, cn, _note, count = cols
        if cat not in GLOSSARY_CATS:
            report.error(where, f'unknown category {cat!r}, '
                                f'expected one of {list(GLOSSARY_CATS)}')
        if not orig:
            report.error(where, 'orig is empty')
        if orig in seen:
            report.error(where, f'{orig!r} is already defined on line {seen[orig]}')
        else:
            seen[orig] = lineno
        if not count.isdigit():
            report.error(where, f'count {count!r} is not a number')
        if any(ch in orig for ch in RUBY_ALL):
            report.error(where, 'orig still holds ruby markup - store the plain term')
        if not cn:
            report.error(where, 'cn is empty')
            continue

        bad = unencodable(cn)
        if bad:
            report.error(where, f'cn {cn!r} holds U+{ord(bad):04X} {bad!r}, '
                                f'which code page 936 can not show')
        kana = KANA_RE.search(cn)
        if kana:
            report.warn(where, f'cn {cn!r} still holds kana {kana.group(0)!r}')
        for ch in JAPANESE_ONLY:
            if ch in cn:
                report.warn(where, f'cn {cn!r} holds Japanese-only {ch!r}')
        if cat in TERM_CATS:
            terms.setdefault(cat, []).append((orig, cn))

    return terms


# --------------------------------------------------------------------------- #
# translated-lines pass
# --------------------------------------------------------------------------- #

def check_ruby(where: str, text: str, orig: str, report: Report) -> None:
    """Ruby markup must stay well formed, or the engine throws in game.

    The check runs on the characters es.TX.RUBY.CHK parses, i.e. on
    ``substitute(text)``; :func:`ruby_errors` is the parser itself.
    """
    text = substitute(text)
    for msg in ruby_errors(text):
        report.error(where, msg)
    spans = ruby_spans(text)
    if len(spans) > MAX_RUBY_SPANS:
        report.error(where, f'{len(spans)} ruby spans, the engine allows '
                            f'{MAX_RUBY_SPANS}')
    for m in RUBY_SPAN_RE.finditer(text):
        body = m.group(1)
        if RUBY_SEP not in body:
            continue            # ruby_errors already explained this one
        base, _sep, reading = body.partition(RUBY_SEP)
        if not base:
            report.error(where, 'a ruby span has an empty base character')
        elif not reading:
            report.error(where, 'a ruby span has an empty reading')
        elif reading == EMPHASIS and len(base) != 1:
            report.error(where, f'emphasis ruby {base!r} covers {len(base)} '
                                f'characters, it must cover exactly one')
    if not orig:
        return
    kept = sum(1 for _b, r in spans if r == EMPHASIS)
    had = sum(1 for _b, r in ruby_spans(orig) if r == EMPHASIS)
    if kept > had:
        report.warn(where, f'{kept} emphasis span(s) but the original has {had}')


def check_terms(where: str, text: str, orig: str,
                terms: dict[str, list[tuple[str, str]]], report: Report) -> None:
    """A term that is in the original should be in the translation as agreed."""
    for cat in TERM_CATS:
        for term, cn in terms.get(cat, ()):
            if term in orig and cn not in text:
                report.warn(where, f'[{cat}] the original holds {term!r}, but the '
                                   f'agreed translation {cn!r} is missing from the '
                                   f'new text')
                return


def check_lines(path: Path, names: set[str], terms: dict[str, list[tuple[str, str]]],
                report: Report, width_ratio: float) -> None:
    rows = read_tsv(path, LINES_HEADER, report)
    if not rows:
        return
    filled = kept = 0
    substitutions = 0
    for lineno, cols in rows:
        where = f'{path.name}:{lineno}'
        if len(cols) != len(LINES_HEADER):
            report.error(where, f'{len(cols)} column(s), expected '
                                f'{len(LINES_HEADER)} - a tab inside a cell?')
            continue
        _id, _count, chars, orig, new = cols
        if not chars.isdigit() or int(chars) != len(orig):
            report.error(where, f'chars {chars!r} does not match the '
                                f'{len(orig)} character(s) of orig_text')
        if not new:
            kept += 1
            continue
        filled += 1

        bad = unencodable(new, allowed=SUBSTITUTIONS)
        if bad:
            report.error(where, f'new_text holds U+{ord(bad):04X} {bad!r}, which '
                                f'code page 936 can not show - the build will '
                                f'refuse this line')
        for ch in SUBSTITUTIONS:
            if ch in new:
                substitutions += new.count(ch)
                report.warn(where, f'new_text holds {ch!r}, the build replaces it '
                                   f'with {SUBSTITUTIONS[ch]!r}')

        check_ruby(where, new, orig, report)

        for ch, pair, effect, fatal in control_hits(new):
            what = (f'which the engine reads as a control code rather than a '
                    f'glyph: {effect}' if fatal else
                    f'a byte pair the engine reserves for control codes: '
                    f'{effect}')
            msg = (f'new_text holds {ch!r} (cp936 {pair}), {what} - reword the '
                   f'line (see glossary/STYLE_GUIDE.md section 4.4)')
            if fatal:
                report.error(where, msg)
            else:
                report.warn(where, msg)

        if RUBY_SEP in RUBY_SPAN_RE.sub('', substitute(new)):
            report.warn(where, f'new_text holds {RUBY_SEP!r} outside a ruby span; '
                               f'es.TX.CHARNAME.CHK cuts the name plate out of a '
                               f'line drawn in the name window at the first '
                               f'{RUBY_SEP!r}, so everything before it would become '
                               f'the name')

        name, mark = plate(orig, names)
        new_name, new_mark = plate(new, names)
        if name:
            if (new_name, new_mark) != (name, mark):
                report.error(where, f'the engine cuts the name {name!r} off a '
                                    f'line that starts with {name + mark!r}, but '
                                    f'this one starts with '
                                    f'{(new_name + new_mark) or new[:12]!r} - the '
                                    f'name plate would stay empty and the whole '
                                    f'line would be painted inside the dialogue '
                                    f'box (see glossary/STYLE_GUIDE.md section 3)')
        elif new_name:
            report.warn(where, f'the original line has no name plate, but this one '
                               f'would show {new_name!r}')

        if orig:
            grew = display_px(new) / max(display_px(orig), 1.0)
            if grew > width_ratio:
                report.warn(where, f'new text is {grew:.2f}x the original '
                                   f'({display_px(new) / FULLWIDTH_PX:.1f} vs '
                                   f'{display_px(orig) / FULLWIDTH_PX:.1f} '
                                   f'fullwidth chars); the dialogue box fits '
                                   f'about {(WRAP_PX - 2 - 2 * DIALOGUE_PX) // DIALOGUE_PX}')
        check_terms(where, new, orig, terms, report)

    report.note(f'{path}: {len(rows)} rows, {filled} translated, '
                f'{kept} kept in Japanese')
    if substitutions:
        report.note(f'{substitutions} character(s) will be swapped by the build')


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def find_names_file(repo: Path) -> Path | None:
    for rel in DEFAULT_NAME_SOURCES:
        candidate = repo / rel
        if candidate.is_file():
            return candidate
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    repo = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        description='Check glossary/glossary.tsv and, with --lines, the '
                    'translated work package before building a pack.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('--glossary', default=str(repo / 'glossary' / 'glossary.tsv'),
                    help='termbase to check')
    ap.add_argument('--lines', help='filled lines.tsv to check (optional)')
    ap.add_argument('--names', help='``キャラ名定義.txt`` holding the es.CHAR.NAME '
                                    'registrations; found automatically by default')
    ap.add_argument('--no-names', action='store_true',
                    help='skip the speaker-prefix check')
    ap.add_argument('--no-terms', action='store_true',
                    help='skip the glossary spelling-consistency check')
    ap.add_argument('--width-ratio', type=float, default=1.25,
                    help='warn when the translation is this much wider than the '
                         'original')
    ap.add_argument('--strict', action='store_true',
                    help='treat warnings as failures')
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = Report()
    repo = Path(__file__).resolve().parent

    glossary = Path(args.glossary).expanduser()
    if not glossary.is_file():
        print(f'error: glossary not found: {glossary}', file=sys.stderr)
        return 2
    terms = check_glossary(glossary, report)

    if args.lines:
        lines = Path(args.lines).expanduser()
        if not lines.is_file():
            print(f'error: lines file not found: {lines}', file=sys.stderr)
            return 2
        if args.no_names:
            names: set[str] = set()
            if not args.no_terms:
                report.note('speaker-prefix check disabled')
        else:
            names_path = (Path(args.names).expanduser() if args.names
                          else find_names_file(repo))
            names = load_names(names_path, report)
        check_lines(lines, names, {} if args.no_terms else terms, report,
                    args.width_ratio)

    summary = f'{report.errors} error(s), {report.warnings} warning(s)'
    if report.errors or (args.strict and report.warnings):
        print(f'FAILED - {summary}')
        return 1
    print(f'ok - {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
