"""Exercise the port of es.TX.RUBY.CHK (check_glossary.ruby_errors) against
every branch it can take.  Run before changing anything ruby-related:

    python test_ruby_check.py        # exit 0 = the parser still matches the engine
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import check_glossary as cg          # noqa: E402

# (name, text, number of complaints the engine would stop on)
CASES = [
    ('plain text',                   '何もない行です。',               0),
    ('prose title, 《》',             '他的《某奇谈》。',                1),
    ('prose title, ≪≫',              '他的≪某奇谈≫。',                 1),
    ('stray 》',                      '还没有开就关了》。',              1),
    ('prose title, 〈〉',             '他的〈某奇谈〉。',                0),
    ('unclosed span',                '《一部分',                        1),
    ('unclosed span with a reading', '《字／じ',                        1),
    ('empty base',                   '《／あ》',                        0),
    ('nested open',                  '《甲《乙／あ》》',                 1),
    ('valid emphasis ruby',          '彼は《呪／·》だ。',                0),
    ('valid reading ruby',           '《字／じ》',                      0),
    ('two spans',                    '《一／い》《二／に》',             0),
    ('fullwidth slash outside',      'a／b 的《字／じ》',                0),
    ('close then open',              '《／》a',                         0),
]

fails = 0
for name, text, want in CASES:
    errs = cg.ruby_errors(cg.substitute(text))
    ok = len(errs) == want
    fails += not ok
    print(f'{"ok " if ok else "BAD"} {name:<30} {len(errs)} (want {want})')
    for e in errs:
        print(f'      {e}')

# check_ruby must agree, and must still flag the per-span details
DETAIL = [
    ('empty reading',         '《甲／》',   True),
    ('empty base',            '《／あ》',   True),
    ('emphasis on two chars', '《呪詛／·》', True),
    ('valid emphasis',        '《呪／·》',   False),
]
print()
for name, text, want in DETAIL:
    rep = cg.Report()
    cg.check_ruby('case', text, '', rep)
    got = bool(rep.errors)
    fails += got != want
    print(f'{"ok " if got == want else "BAD"} {name:<24} errors={rep.errors}')

print()
print('substitute():', repr(cg.substitute('\u226a\u5b57\uff0f\u00b7\u226b')))
print('display_px of ruby:', cg.display_px('\u226a\u5b57\uff0f\u3042\u3044\u226b'))
print('fails:', fails)
raise SystemExit(1 if fails else 0)
