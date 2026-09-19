"""Exercise check_glossary.control_hits against es.TX.CRPREPLACE.

``es.TX.CRPREPLACE`` (``es_text.yst``:991-1075) reads four cp936 byte pairs as
draw markers instead of glyphs.  Shift-JIS leaves those pairs unassigned, so the
Japanese original can never hold one - but a Chinese translation can, and the
line then renders silently one character short.  Run this before touching the
table:

    python test_control_check.py     # exit 0 = the table still matches cp936
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import check_glossary as cg          # noqa: E402

CONTROL_BYTES = {pair: ch for ch, (pair, _eff, _fat) in cg.CONTROL_CHARS.items()}

fails = 0


def case(name: str, got, want) -> None:
    global fails
    ok = got == want
    fails += not ok
    print(f'{"ok " if ok else "BAD"} {name:<40} {got!r} (want {want!r})')


# ---- the table itself must be exactly the cp936 pairs the engine reads -----
# Build the full cp936 two-byte table and collect every character that decodes
# to one of the control pairs.  If the engine ever gains a pair, or a table
# entry is mistyped, this is what goes red.
found: dict[str, str] = {}
for lead in range(0x81, 0xFF):
    for trail in range(0x40, 0xFF):
        try:
            ch = bytes([lead, trail]).decode('cp936')
        except UnicodeDecodeError:
            continue
        if f'{lead:02X} {trail:02X}' in CONTROL_BYTES:
            found[f'{lead:02X} {trail:02X}'] = ch

case('cp936 spells each control pair with', found, CONTROL_BYTES)


def decodable(lead: int) -> int:
    n = 0
    for trail in range(0x40, 0xFF):
        try:
            bytes([lead, trail]).decode('cp936')
        except UnicodeDecodeError:
            continue
        n += 1
    return n


# the four pairs sit in the 0xEF lead block; the other 186 characters that share
# that lead byte are ordinary glyphs, which is why only an exact pair collides
case('characters in the 0xEF block', decodable(0xEF), 190)

# the premise: shift-jis leaves the pairs free, so the original text cannot hit them
jp = [p for p in CONTROL_BYTES
      if bytes(int(b, 16) for b in p.split()).decode('cp932', 'ignore')]
case('cp932 decodes any control pair', jp, [])

for ch, (pair, _effect, _fatal) in cg.CONTROL_CHARS.items():
    case(f'bytes of {ch}', f'{ch.encode("cp936")[0]:02X} {ch.encode("cp936")[1]:02X}', pair)

# ---- control_hits ---------------------------------------------------------
HITS = [
    ('plain Chinese prose',      '\u4ed6\u7684\u300a\u5168\u666f\u5c9b\u5947\u8c08\u300b\u3002', 0),
    ('\u9573 in \u5206\u9053\u626c\u9573',  '\u5206\u9053\u626c\u9573',   1),
    ('\u77e7',                   '\u77e7\u4e0d\u53ca',                 1),
    ('\u77ec',                   '\u77ec\u5b50',                       1),
    ('\u953a draws, never matches', '\u953a',                          1),
    ('\u956f (EF ED) is harmless',  '\u956f\u5b50',                     0),
    ('full width punctuation',   '\u300c\u4e00\u300d\u2014\u2014\u3001\u3002', 0),
    ('ascii',                    'HP/MP 100%',                         0),
]
for name, text, want in HITS:
    got = len(cg.control_hits(text))
    fails += got != want
    print(f'{"ok " if got == want else "BAD"} control_hits {name:<38} {got} (want {want})')

# ---- severity -------------------------------------------------------------
for name, text, want_errors, want_warns in [
        ('fatal \u9573',      '\u5206\u9053\u626c\u9573', 1, 0),
        ('reserved \u953a',   '\u953a',                    0, 1),
        ('clean',             '\u5e73\u5e38\u5fc3',       0, 0)]:
    rep = cg.Report()
    for ch, _pair, _effect, fatal in cg.control_hits(text):
        (rep.error if fatal else rep.warn)('case', repr(ch))
    case(name, (rep.errors, rep.warnings), (want_errors, want_warns))

# ---- end to end through check_lines --------------------------------------
# one fatal row, one reserved row, one stray full-width slash, one clean row
rows = [
    ('1', '\u9375', '\u5206\u9053\u626c\u9573'),
    ('1', '\u9418', '\u953a'),
    ('1', '\u3042', 'a\uff0fb'),
    ('1', '\u3044', '\u5e73\u5e38\u5fc3'),
]
tmp = Path(tempfile.mkdtemp()) / 'lines.tsv'
body = ['\t'.join(cg.LINES_HEADER)]
body += ['\t'.join([str(i), count, str(len(orig)), orig, new])
         for i, (count, orig, new) in enumerate(rows, 1)]
tmp.write_bytes(('\ufeff' + '\n'.join(body) + '\n').encode('utf-8'))


class Capture(cg.Report):
    """Report that also keeps the messages, so a check can be told apart from
    the width warnings the same rows produce."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.messages.append(msg)
        super().error(where, msg)

    def warn(self, where: str, msg: str) -> None:
        self.messages.append(msg)
        super().warn(where, msg)


rep = Capture()
cg.check_lines(tmp, set(), {}, rep, 1.25)
ctrl = [m for m in rep.messages if 'control code' in m]
case('check_lines control complaints', len(ctrl), 2)          # row 1 fatal, row 2 reserved
case('check_lines fatal rows', rep.errors, 1)
case('check_lines slash warning',
     sum('name plate' in m for m in rep.messages), 1)         # row 3
print('     ', ctrl[0][:110] if ctrl else '(no control complaint)')

print()
print('fails:', fails)
raise SystemExit(1 if fails else 0)
