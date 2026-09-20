#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-encode the *engine* scripts of a YU-RIS game from CP932 into GBK.

Why this exists
---------------
The scenario scripts (``data\\script\\userscript\\*``) are rebuilt by
``inject_yuris_text.py`` and shipped in code page 936, but the *engine* scripts
(``eris``, ``userdefine``, ``puserdefine``, ``puserdesign`` - the 182 lowest
script indices) were never touched and are still Shift-JIS.  The patched
executable now asks GDI for code page 936, so every one of those bytes is read
with the wrong table.  Two things break:

  * **Strings the engine draws** - the menu labels, the engine's window captions,
    the notes it prints (``[エラー] ... ルビ記述エラーです。``) - turn into
    mojibake.
  * **Strings that are compared against player text** - the ruby delimiters
    ``≪`` ``／`` ``≫``, the per character metric tweaks for ``、「」。『』（）``,
    the quote the first line is measured against - stop matching, because the
    text is now GBK.  Ruby markup is drawn literally instead of above the base
    text and punctuation loses its spacing.

The fix is the same re-encoding the scenario text already went through, applied
in place: decode every string literal as CP932, apply ``SUBSTITUTIONS`` (the four
characters with no GBK mapping), encode with the *system* CP936 table and write
the bytes back at their original offset.

Except for the text a *dialog box* shows
----------------------------------------
There are two independent text paths in this engine, and only one of them listens
to the executable's character set:

* what the engine **draws** goes through GDI ``TextOutA`` and is decoded with the
  character set of the font, which ``patch_yuris_charset.py`` sets to 0x86
  (GB2312) - that is why everything else here is re-encoded;
* what a **dialog box** shows is handed to the ANSI Win32 API
  (``MessageBoxA`` / ``DialogBoxParamA`` / ``SetWindowTextA`` / ``SendMessageA``),
  which decodes with the *process* code page - the system one, 932 here, whatever
  the patched font says.

So re-encoding the dialog literals is what turns the caption ``終了確認`` into
``ｽKﾁﾋｴ_ﾕJ`` (GBK bytes read as Shift-JIS).  This pass therefore leaves the
literals of that second path in Shift-JIS: the dialog ones described in
:data:`UI_CMD`, together with the file that only defines them (:data:`UI_SCRIPTS`)
and the ``確認`` captions the confirm scenes park in a variable before the call
(:data:`UI_LITERALS`).  Shift-JIS
cannot carry simplified Chinese, so those strings stay Japanese until the
executable is taught to convert them - that is a separate, executable level change
and not something a script re-encode can do.

Why in place - and why that is provably safe
--------------------------------------------
A kana, a kanji and a kanji punctuation mark are two bytes in CP932 and two
bytes in GBK, ASCII stays one byte, and all four substitutions are two bytes.
So every literal keeps its original length, which means no offset, size, branch
target, line number or command index in the file has to move: the command
block, the line number block and the whole argument block come out byte
identical and only the bytes *inside* a literal change.  :func:`transcode_script`
checks exactly that after every rewrite (see the ``expected`` block below) and
refuses to write a file that does not pass.

The font face name is *renamed*, not re-encoded
-----------------------------------------------
Every face name in these scripts is the same literal - ``ＭＳ ゴシック``, 13 bytes
of CP932 - and the engine hands those bytes straight to ``CreateFontA``.  A
GBK-encoded copy of the same characters is a different byte run, so it matches no
installed font and the font mapper quietly substitutes one; that substitution is
what the player sees as uneven stroke weights, because the Latin/Chinese
characters come from the substitute while the rare Japanese ones are font-linked
from a second face.

This pass therefore replaces the name itself with ``--face`` (default
:data:`FACE_TARGET`), NUL-padded back to the original 13 bytes so the literal -
and every offset after it - keeps its length.  GDI stops reading a face name at
the NUL, and the engine's name buffers are zero filled, so the padding is
invisible.  ``install_glow_sans.py`` registers a font under exactly that name;
the two belong together - a pack built with a face name the system does not have
is the substitution bug above, all over again.

The dialogue size is *patched*, not re-encoded
----------------------------------------------
The size a text definition draws with is not a string but an integer operand of
``GOSUB[#="es.TD.SIZE.SET" PINT=<width> PINT2=<height>]`` in
``userdefine\\文字定義.txt``; the ``GOSUB[#="es.TDDEF.SET" PSTR="<name>"]`` a few
calls later commits the staged values under the name the engine then looks up
(``M`` is the ADV dialogue, ``NAME`` the speaker plate, ``M_TATE`` the vertical
one).  The size of a definition is therefore the ``es.TD.SIZE.SET`` that precedes
its ``es.TDDEF.SET``, and ``--td-size`` writes that operand in place.  Every one
of them is a single byte, so a different value moves nothing in the file either -
and the read-back at the end of :func:`transcode_script` proves the new size is
where it was asked to be.  Every definition that is not named keeps exactly its
original size, which is why the menus and the system text stay as they are.

The two operands are not the same thing.  ``PINT`` is the width of the cell the
pen advances by, ``PINT2`` the height the glyph is drawn at, and the engine's font
builder passes ``lfHeight=PINT2`` with ``lfWidth=0`` to ``CreateFont`` -
so the glyph keeps its natural proportions and the width never squeezes it.  Since
``lfHeight`` is scaled by the face's own ascent+descent, only a face whose
line metrics are 1 em draws the ink its size asks for: ``ＭＳ ゴシック`` is
exactly 1 em (220/-36 of 256), while Glow Sans SC ships 1160/-288 = 1.448 em and
wants ``--line-metrics typo`` (880/-120) before any size makes sense.  Once that
holds, the ink of Glow Sans SC is *narrow* relative to its advance (0.812 em
against 0.852), so the shipped value is a *tall* ``PINT2`` over a *narrow*
``PINT`` (``M=30x32``, not a square): the narrow cell takes the slack out of the
gaps between two full width characters while the tall cell keeps the glyphs the
size they should be.  ``NAME=WxH`` sets the two apart; ``NAME=SIZE`` is the square
cell the game itself uses.

The line and letter spacing are patched the same way
---------------------------------------------------
How tightly the text sits is not a property of the text definition: the renderer
adds ``@gInt1144(36,19)`` pixels to every advance and ``@gInt1144(36,20)`` pixels
to every line, so those two integers are the only lever and they are global.
``--char-space`` and ``--line-space`` write them where the engine assigns them
(``userdefine\\メイン定義.txt``), which is a ``LET`` of a constant - one byte
again, and the read-back proves it.  A wide face whose glyphs do not fill their
cell needs a negative letter spacing; the game ships -2.

Four families of literals keep their CP932 bytes on purpose.

  * **Resource names** (:func:`is_resource_like`): ``tip/文鳴_コート_通常_右``,
    ``cgsys/extra/cgmode/num_ページ数/num_``, ``00_プロローグ.txt``,
    ``C:\\Program Files\\...exe``.  The engine matches those byte for byte
    against the archive index and the script table, so re-encoding one would
    make it fail to find the picture, the voice or the script it is asking for.
    The check is a slash, a backslash or an asset extension - deliberately
    over-eager, because a lost image is worse than one error message left in
    Shift-JIS.  The over-eager cases that are really prose (:data:`DISPLAY_CP932`:
    ``■BGM/SE VOL+``, the engine's own "you called me wrong" notes) are listed
    out and re-encoded anyway.
  * **Label names** (:func:`collect_label_names`): ``４５４５定義``, ``CM_QUAK_左1``,
    ``BGM_全消去``.  A ``GOSUB`` names its target with a *string* - sometimes
    directly, sometimes by parking it in a variable first - and the engine
    resolves that string against the label table ``ysl.ybn``, a file this pack
    does not ship, so the table keeps spelling every name in Shift-JIS.  A
    re-encoded reference makes the lookup compare ``A3B4A3B5...`` against
    ``82538254...`` and fail: ``es_select2.yst`` aborted the chapter select with
    ``ラベル ｣ｴ｣ｵ｣ｴ｣ｵｶｨﾁx が 見つかりませんでした`` (its ``GOSUB`` names
    ``４５４５定義``), and the same failure made every non-ASCII macro the
    ``userdefine`` scripts define - the camera and quake patterns, the
    ``全消去`` commands - unreachable.  A label name is an identifier the engine
    matches byte for byte, so it belongs with the resource names above.
  * **Literals an OS dialog box shows** - whatever a ``DIALOG`` command owns
    (``"アプリケーションを終了します。宜しいですか？"``, ``"終了確認"``,
    ``"デバッグ機能"``), the arguments of the ``GOSUB`` wrappers that forward them
    (:data:`UI_GOSUB_LABELS`), the file that only defines the confirm questions
    (:data:`UI_SCRIPTS`) and the confirm captions that go through a variable
    (:data:`UI_LITERALS`).  This is the family the section above is about: those
    bytes are read with the system code page, not with code page 936.
  * **Literals a scenario script also uses** (the shared-literal scan over every
    index above ``--max-idx``).  A scenario passes such a string - ``なし``, a
    shake pattern name - to an engine routine that compares it with its own
    literal.  The scenario keeps its CP932 bytes (``inject_yuris_text.py`` only
    rewrites dialogue), so the engine literal has to stay CP932 too or the
    comparison silently stops matching.

Usage::

    # write just the engine scripts that change into an overlay folder
    python transcode_yuris_scripts.py --indir D:\\ysbin --outdir build\\ysbin

    # ... and list what could not be re-encoded
    python transcode_yuris_scripts.py --indir D:\\ysbin --outdir build\\ysbin \\
        --report build\\engine_transcode.tsv

    # ... and render with another face (must be installed and <= 12 bytes)
    python transcode_yuris_scripts.py --indir D:\\ysbin --outdir build\\ysbin \\
        --face "Glow Sans SC"

    # ... and draw the dialogue bigger while the menus keep their size
    python transcode_yuris_scripts.py --indir D:\\ysbin --outdir build\\ysbin \\
        --td-size "M=30x32, NAME=30x32"

    # ... and close the gaps a wide face leaves between the characters
    python transcode_yuris_scripts.py --indir D:\\ysbin --outdir build\\ysbin \\
        --char-space -6

``build_cn_pack.py`` runs this automatically between the injection and the
packing step.  Only scripts that really changed are written out, so the shipped
``update1.ypf`` is an *overlay*: whatever it does not carry is still read from
the game's own ``pac\bn.ypf``.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

try:
    import extract_yuris_text as ex
    import inject_yuris_text as inj
    import transcode_yuris_gbk as tg
except ImportError:  # pragma: no cover
    print('error: transcode_yuris_scripts.py must live next to '
          'inject_yuris_text.py and transcode_yuris_gbk.py', file=sys.stderr)
    raise SystemExit(1)

#: ``Ins`` opcode of a string literal; ``SIns`` is ``'<BH'`` (opcode, size).
INS_STR = 0x4D
INS_HEADER = 3
#: The ``Ins`` opcodes that hold a plain integer, with their width in bytes.
INS_INT_WIDTHS = {0x42: 1, 0x57: 2, 0x49: 4, 0x4C: 8}
#: The two calls a text definition is built from in ``userdefine\文字定義.txt``:
#: one stages the values, the other commits everything staged under a name.
TD_SIZE_CMD = 'es.TD.SIZE.SET'
TD_DEF_CMD = 'es.TDDEF.SET'
#: ``LET`` is how an engine script assigns a global, and the two ``gInt1144``
#: fields below are the whole of the text renderer's spacing: ``es_text.yst``
#: builds every character advance as ``cell width + @gInt1144(36,19)`` and every
#: line advance as ``glyph height + @gInt1144(36,20)``.
LET_CMD = 'LET'
#: ``Ins`` opcode of "negate what is on the stack" - ``-2`` is stored as the
#: constant ``2`` followed by this, so the sign costs a byte of its own.
INS_NEG = 0x52
#: The font slot every text definition falls back to, and its spacing fields:
#: 19 is the letter spacing (字間), 20 the line spacing (行間), both in pixels.
FONT_SLOT = 36
CHAR_SPACE_FIELD = 19
LINE_SPACE_FIELD = 20
#: Highest script index that belongs to the engine (``userscript`` starts at 182).
DEFAULT_MAX_IDX = 181
#: The aliases of the engine's code page.
CP936_ALIASES = ('gbk', 'cp936', '936', 'ms936')

#: The face name every engine script stores, in CP932: 2 + 2 + 1 + 2 + 2 + 2 + 2
#: bytes.  It is a fixed width slot - the literal cannot grow - so a replacement
#: has to fit in 13 bytes.
FACE_SOURCE = 'ＭＳ ゴシック'
#: What the pack hands to ``CreateFontA`` instead.  Registered by
#: ``install_glow_sans.py``; 12 ASCII bytes, so it fits with one NUL to spare.
#: Unlike the exe's face table there is no fallback chain here: on a machine
#: without the family GDI silently substitutes (SimSun), so the dialogue keeps
#: working but looks different - see glossary/STYLE_GUIDE.md section 8.7.
FACE_TARGET = 'Glow Sans SC'
#: Highest number of bytes a face name may occupy, i.e. ``len(FACE_SOURCE)``.
FACE_BYTES = len(FACE_SOURCE.encode('cp932'))


def face_literal(name: str) -> bytes:
    """The stored bytes for face *name*: ASCII, NUL padded to the fixed slot."""
    raw = name.encode('ascii', 'strict')
    if not raw or len(raw) > FACE_BYTES:
        raise ValueError(f'face name {name!r} does not fit in {FACE_BYTES} bytes')
    if b'"' in raw or b'\x00' in raw:
        raise ValueError(f'face name {name!r} contains a quote or a NUL')
    return raw.ljust(FACE_BYTES, b'\x00')


def parse_td_sizes(spec: str) -> dict[str, tuple[int, int]]:
    """``"M=32, NAME=33x42"`` -> ``{'M': (32, 32), 'NAME': (33, 42)}``.

    The names are the ones ``es.TDDEF.SET`` commits in
    ``userdefine\\文字定義.txt``; a value is the character cell the engine draws
    with, in pixels - one number for a square cell, or ``WIDTHxHEIGHT`` for the
    two operands of ``es.TD.SIZE.SET`` separately (the width is the pen advance,
    the height the glyph height).  An empty spec is no sizes at all.
    """
    out: dict[str, tuple[int, int]] = {}
    for item in spec.replace(',', ' ').split():
        name, sep, value = item.partition('=')
        if not sep or not name:
            raise ValueError(f'{item!r} is not a NAME=SIZE pair')
        try:
            parts = [int(part, 0) for part in value.lower().split('x')]
        except ValueError:
            raise ValueError(f'{item!r} does not end in a number') from None
        if len(parts) == 1:
            parts *= 2
        if len(parts) != 2:
            raise ValueError(f'{item!r} is not NAME=SIZE or NAME=WIDTHxHEIGHT')
        for part in parts:
            if not 1 <= part <= 0xFFFF:
                raise ValueError(f'{item!r}: a text size has to be 1..65535')
        out[name] = (parts[0], parts[1])
    return out


FACE_SOURCE_BYTES = FACE_SOURCE.encode('cp932')

#: A literal that names something the engine looks up by bytes rather than a
#: string it shows: it holds a slash or a backslash (``tip/文鳴_コート_通常_右``,
#: ``cgsys/extra/cgmode/num_ページ数/num_``, ``00_プロローグ.txt``,
#: ``C:\\Program Files\\...exe``) or ends in an asset extension.  Re-encoding one
#: of those would make the engine fail to find the picture, the folder or the
#: script it is asking for - a lost image is worse than one error message left in
#: Shift-JIS, so the rule stays deliberately over-eager.
RESOURCE_RE = re.compile(
    r'[/\\]|\.(?:png|bmp|jpg|jpeg|gif|webp|wav|ogg|mp3|avi|mpg|mpeg|txt|csv|dat'
    r'|ypf|ybn|exe|dll|ini|tbl)$', re.I)

#: Literals :data:`RESOURCE_RE` would hold back even though they are *prose*: the
#: volume labels on the config screen and the notes the engine prints when a
#: script calls it wrong.  Nothing looks them up, so they are re-encoded and read
#: correctly if they ever reach the screen.  Written as a raw string so the
#: backslashes match the stored bytes (the scripts really do say ``\\DBG.VAR``).
#: Checked against all 174 engine scripts - every other slash in there is part of
#: a real path.  One deliberate hold-out: ``/※ｽｸﾘﾌﾟﾄﾌｧｲﾙ名...`` continues the
#: ``/  あります`` note that *is* listed below, and halfwidth katakana cannot be
#: re-encoded without growing the literal, so it stays CP932 to keep the note in
#: one encoding.
#:
#: Messages that *are* listed here but go to ``es._mes`` - ``S.RETURN エラー...``
#: and the ``\\SP*.DEF`` notes - are not in this list any more: they are shown by
#: an OS dialog box, which the rules above already look after.
DISPLAY_CP932: frozenset[str] = frozenset(
    s.strip() for s in r"""
    ■BGM/SE VOL+
    ■BGM/SE VOL-
    /  あります。目安程度としてご了承ください。あと秀丸TagJumpに対応してます
    \\DBG.STR.GNO および \\DBG.STR.LNO の定義を全て消していただき、
    の、\\DBG.STR.GNO および \\DBG.STR.LNO の定義は、
    代わりに \\DBG.VAR 命令に
    別途違う命令( \\DBG.VAR )でおこなう形になりました。
""".splitlines() if s.strip())


#: The command whose string arguments a dialog box shows, and the command that
#: jumps to a wrapper doing the same.  Everything below is about the *other* text
#: path: a ``DIALOG`` is not drawn by the engine, it is an ANSI Win32 dialog
#: (``MessageBoxA`` / ``DialogBoxParamA`` / ``SetWindowTextA``) and the operating
#: system decodes its bytes with the process code page (932 on a Japanese
#: Windows, whatever ``patch_yuris_charset.py`` does to the font).  Those literals
#: therefore have to stay Shift-JIS - unless the executable is changed to convert
#: them, which is a separate piece of work.
UI_CMD = 'DIALOG'
UI_GOSUB_CMD = 'GOSUB'
#: ``GOSUB`` labels whose string arguments end up in a ``DIALOG``:
#: ``es._mes`` (the engine's own error boxes) and the ``es.DIALOG.*`` /
#: ``es.INPUT.STR.SET`` wrappers in ``eris\stdlib\ystdlib.yst``.  Every call site
#: in this game passes its text as a literal, so following the label is enough.
UI_GOSUB_LABELS: frozenset[str] = frozenset((
    'es._mes',
    'es.DIALOG.SET',
    'es.DIALOG.YESNO.SET',
    'es.DIALOG.YESNOCANCEL.SET',
    'es.DIALOG.OKCANCEL.SET',
    'es.INPUT.STR.SET',
))
UI_GOSUB_LABEL_BYTES: frozenset[bytes] = frozenset(
    label.encode('cp932') for label in UI_GOSUB_LABELS)
#: Script paths (as ``yst_list.ybn`` spells them) that only define strings a
#: ``DIALOG`` shows - every literal in them is dialog text, so all of them stay
#: Shift-JIS.  ``puserdefine\確認定義.txt`` holds the 15 confirm questions
#: (``$gStr1145(13,N)``) that the confirm scenes pass to their ``DIALOG``.
UI_SCRIPTS: tuple[str, ...] = ('確認定義.txt',)
#: Literals that reach a dialog through a *variable* rather than through the
#: command's own argument, so the rule above cannot see them.  The confirm scenes
#: clear the engine window caption (``WINDOWINFO[NO=0 CAPTION=1 ...]``) and then
#: park the caption of the box in the same variable before calling the ``DIALOG``
#: (``$vStr4376="確認"``) - see ``es_endconf.yst`` and its eight siblings.  An
#: exact string is the honest way to describe that: ``確認`` appears nowhere else
#: in the engine scripts, and the report tells us if that ever changes.
UI_LITERALS: tuple[str, ...] = ('確認',)
#: ``Stats.kept`` reasons for the two rules above.
WHY_UI_CMD = 'shown by an OS dialog box'
WHY_UI_LITERAL = 'a caption an OS dialog box shows'
#: ``Stats.kept`` reason for a literal that names a label - an identifier the
#: engine resolves against the Shift-JIS label table (see
#: :func:`collect_label_names`).
WHY_LABEL = 'a label name (ysl.ybn spells them in CP932)'


def strip_quotes(data: bytes) -> bytes:
    """The literal without the quotes that are part of the stored payload."""
    if len(data) >= 2 and data[:1] == b'"' and data[-1:] == b'"':
        return data[1:-1]
    return data


def literal_text(raw: bytes) -> str:
    """The stored payload as text, without the surrounding quotes."""
    return strip_quotes(raw).decode('cp932', 'replace')


def is_prose(raw: bytes) -> bool:
    """True when the payload is one of the :data:`DISPLAY_CP932` exceptions."""
    return literal_text(raw) in DISPLAY_CP932


def is_resource_like(raw: bytes) -> bool:
    """True when the literal payload *raw* (quotes included) names a file, a
    folder or a script rather than a string the engine shows."""
    text = literal_text(raw)
    if text in DISPLAY_CP932:
        return False
    return bool(RESOURCE_RE.search(text))


class Stats:
    """Per script counters, also used to build the report."""

    __slots__ = ('literals', 'changed', 'kept', 'left', 'subs', 'prose',
                 'dialogs', 'gosubs', 'faces', 'td_sizes', 'spaces')

    def __init__(self) -> None:
        self.literals = 0              # string literals seen
        self.changed = 0               # literals whose bytes changed
        self.kept: list[tuple[str, str]] = []   # (reason, literal) left in CP932
        self.left: list[tuple[str, str]] = []   # (literal, why it was skipped)
        self.subs: dict[str, int] = {}  # substitution hits
        self.prose: set[str] = set()    # DISPLAY_CP932 entries that matched
        self.dialogs = 0               # DIALOG commands (dialog text found here)
        self.gosubs = 0                # GOSUB calls into a dialog wrapper
        self.faces = 0                 # face-name literals renamed
        self.td_sizes: list[str] = []  # text size operands rewritten
        self.spaces: list[str] = []    # text spacing operands rewritten

    def note_sub(self, ch: str, n: int) -> None:
        self.subs[ch] = self.subs.get(ch, 0) + n


def ins_records(ff, payload: bytes):
    """Walk the ``Ins`` records of one argument payload.

    An argument's expression data is a flat list of ``Ins`` records, each
    ``opcode (u8) + size (u16) + size bytes`` - the same walk the engine and
    ``yurislib`` do, so every doubt about the layout aborts the file instead of
    corrupting it.  Yields ``(opcode, start, end, value)`` per record, where
    *start*/*end* delimit the bytes after the header inside *payload*.
    """
    pos = 0
    n = len(payload)
    while pos < n:
        if pos + INS_HEADER > n:
            raise ValueError('an expression record runs past the end of its payload')
        code = payload[pos]
        size = int.from_bytes(payload[pos + 1:pos + 3], 'little')
        end = pos + INS_HEADER + size
        if end > n:
            raise ValueError(f'expression instruction 0x{code:02x} wants {size} '
                             f'byte(s) but only {n - pos - INS_HEADER} are left')
        known = ff.InsList.get(code)
        if known is None:
            raise ValueError(f'unknown expression instruction 0x{code:02x}')
        if known[0] >= 0 and known[0] != size:
            raise ValueError(f'expression instruction {known[1]} has size {size}, '
                             f'expected {known[0]}')
        yield code, pos + INS_HEADER, end, payload[pos + INS_HEADER:end]
        pos = end
    if pos != n:
        raise ValueError('the expression walk desynced')


def literal_ranges(ff, payload: bytes) -> list[tuple[int, int]]:
    """Where the string literals sit inside one argument payload."""
    return [(start, end) for code, start, end, _value in ins_records(ff, payload)
            if code == INS_STR]


def transcode_literal(data: bytes, src: str, encoding: str = 'gbk'
                      ) -> tuple[bytes, dict[str, int]]:
    """Return ``(gbk bytes, substitution hits)`` for one CP932 literal.

    Raises :class:`UnicodeDecodeError` when the bytes are not CP932 and
    :class:`UnicodeEncodeError` / :class:`ValueError` when the result would not
    be the same length - the caller turns that into "leave this literal alone".
    """
    text = data.decode(src)
    mapped, hits = tg.substitute(text)
    if encoding in CP936_ALIASES:
        blob = tg.windows_cp936_encode(mapped)
    else:  # pragma: no cover - the engine only speaks code page 936
        blob = mapped.encode(encoding)
    if len(blob) != len(data):
        raise ValueError(f'{len(data)} byte(s) of {src} became {len(blob)} '
                         f'byte(s) of {encoding}')
    return blob, hits


def decodes_as_gbk(data: bytes) -> bool:
    """True when *data* is already a valid code page 936 byte sequence."""
    try:
        data.decode('gbk')
    except UnicodeDecodeError:
        return False
    return True


def collect_shared_literals(files, ff, key: int, kcc, min_idx: int,
                            src: str = 'cp932') -> frozenset[bytes]:
    """CP932 literals that the scenario scripts hand to engine routines.

    Only literals that live in *argument expressions* count.  A dialogue line is
    a ``WORD`` payload that the pack already ships in GBK, so it is not a CP932
    partner an engine literal has to keep matching.
    """
    shared: set[bytes] = set()
    for p in files:
        idx = inj.script_index(p.name)
        if not idx or int(idx) < min_idx:
            continue
        try:
            _v, ncmd, (cmd, arg, expr, _lnos) = inj.read_blocks(p.read_bytes(),
                                                                ff, key)
            owners, words, _dummies = inj.walk_layout(
                cmd, ncmd, kcc, len(arg) // inj.ARG_SIZE)
            for j in owners:
                if j in words:
                    continue
                _kid, _typ, _aop, siz, off = struct.unpack_from(
                    inj.ARG_FMT, arg, inj.ARG_SIZE * j)
                if off + siz > len(expr):
                    continue
                payload = bytes(expr[off:off + siz])
                for start, end in literal_ranges(ff, payload):
                    data = strip_quotes(payload[start:end])
                    if data and any(b >= 0x80 for b in data):
                        shared.add(data)
        except Exception:
            continue    # an unreadable scenario only costs us a keep decision
    return frozenset(shared)


def collect_label_names(indir: Path, ff, src: str = 'cp932'
                        ) -> frozenset[str]:
    """The names in the label table ``ysl.ybn``.

    A ``GOSUB``/``GOTO`` carries the name of its target as a *string* and the
    engine resolves that string against this table, so a reference and its
    definition have to be spelled the same way.  The table is not part of the
    pack, which means its names stay in Shift-JIS and every reference has to stay
    in Shift-JIS as well - see the module docstring.
    """
    try:
        with open(indir / 'ysl.ybn', 'rb') as fp:
            ysl = ff.YSLB(ff.Rdr(fp.read(), enc=src))
    except Exception as e:  # a missing table only costs us a keep decision
        inj.warn(f'could not read {indir / "ysl.ybn"} ({type(e).__name__}: {e}) '
                 f'- literals that name a label can not be recognised')
        return frozenset()
    return frozenset(l.name for l in ysl.lbls)


def command_records(cmd, ncmd: int, kcc, nrecords: int
                    ) -> list[tuple[int, int, int, int]]:
    """``[(cmd_index, code, first_record, record_count), ...]`` for every command.

    The same dispatch :func:`inject_yuris_text.walk_layout` does - ``RETURNCODE``
    takes one placeholder record, ``IF``/``ELSE`` with three operands keep two
    branch arms behind their condition, ``LOOP`` one, everything else owns as many
    records as it has arguments - so a caller can ask "which records belong to this
    command?" without walking the table a second way.  Rabidly strict on purpose:
    a walk that does not consume exactly *nrecords* records raises.

    A command without arguments consumes no record at all, so for the last command
    of a script ``first_record`` is ``nrecords`` - callers that want records have
    to look at ``record_count`` first.
    """
    out: list[tuple[int, int, int, int]] = []
    ai = 0
    for i in range(ncmd):
        code, narg = cmd[4 * i], cmd[4 * i + 1]
        if code == kcc.RETURNCODE:
            n = 1
        elif code in (kcc.IF, kcc.ELSE) and narg == 3:
            n = 3
        elif code == kcc.LOOP:
            n = 2
        else:
            n = narg
        out.append((i, code, ai, n))
        ai += n
    if ai != nrecords:
        raise ValueError(f'argument walk desynced ({ai} of {nrecords} records)')
    return out


def record_literals(ff, arg, expr, record: int) -> list[bytes]:
    """The bare string literals of one argument record (quotes stripped)."""
    _kid, _typ, _aop, siz, off = struct.unpack_from(
        inj.ARG_FMT, arg, inj.ARG_SIZE * record)
    if off + siz > len(expr):
        raise ValueError(f'argument record {record} points outside the '
                         f'expression block ({off}+{siz} > {len(expr)})')
    payload = bytes(expr[off:off + siz])
    return [strip_quotes(payload[start:end])
            for start, end in literal_ranges(ff, payload)]


def record_items(ff, arg, expr, record: int,
                 words: frozenset[int] = frozenset()
                 ) -> tuple[list[str], list[tuple[int, int, int, int]]]:
    """``(literals, integer operands)`` of one argument record.

    A ``WORD`` payload *is* the string (``words`` holds the record indices that
    are); every other payload is expression data whose ``str`` instructions hold
    the text.  Each integer operand comes back as ``(offset, opcode, width,
    value)`` with the offset into the expression block, so a caller can rewrite
    the value in place.
    """
    _kid, _typ, _aop, siz, off = struct.unpack_from(
        inj.ARG_FMT, arg, inj.ARG_SIZE * record)
    if off + siz > len(expr):
        raise ValueError(f'argument record {record} points outside the '
                         f'expression block ({off}+{siz} > {len(expr)})')
    payload = bytes(expr[off:off + siz])
    if record in words:
        return [strip_quotes(payload).decode('cp932', 'replace')], []
    lits: list[str] = []
    ints: list[tuple[int, int, int, int]] = []
    for code, start, end, value in ins_records(ff, payload):
        if code == INS_STR:
            lits.append(strip_quotes(value).decode('cp932', 'replace'))
        elif code in INS_INT_WIDTHS:
            ints.append((off + start, code, end - start,
                         int.from_bytes(value, 'little', signed=True)))
    return lits, ints


def td_size_sites(ff, cmd, ncmd: int, kcc, arg, expr, owners, words: frozenset[int],
                  targets: frozenset[str]
                  ) -> dict[str, list[list[tuple[int, int, int, int]]]]:
    """Where each named text definition keeps its ``es.TD.SIZE.SET`` operands.

    ``userdefine\\文字定義.txt`` builds a text definition by *staging* it - a run
    of ``es.TD.*.SET`` calls - and then *committing* the staged values under a
    name with ``es.TDDEF.SET``, so the size of a definition is the
    ``es.TD.SIZE.SET`` that precedes its ``es.TDDEF.SET``.

    Returns ``name -> [[(offset, opcode, width, value), ...], ...]``: one inner
    list per commit, its operands in the order the script staged them, so element
    0 is the ``PINT`` (the advance the pen moves by) and element 1 the ``PINT2``
    (the glyph height).  Offsets are into the expression block; every operand is
    a single byte ``i8``, so writing a different one moves nothing in the file.

    Only *owners* (see :func:`inject_yuris_text.walk_layout`) hold expression
    data - a ``RETURNCODE`` placeholder keeps a return code in the fields an
    expression would use, so it is skipped rather than parsed.
    """
    out: dict[str, list[list[tuple[int, int, int, int]]]] = {}
    staged: list[tuple[int, int, int, int]] = []
    keep = set(owners)
    for _i, _code, first, count in command_records(cmd, ncmd, kcc,
                                                   len(arg) // inj.ARG_SIZE):
        if not count:
            continue
        lits: list[str] = []
        ints: list[tuple[int, int, int, int]] = []
        for j in range(first, first + count):
            if j not in keep:
                continue
            record_lits, record_ints = record_items(ff, arg, expr, j, words)
            lits.extend(record_lits)
            ints.extend(record_ints)
        if TD_SIZE_CMD in lits:
            staged = ints
        elif TD_DEF_CMD in lits:
            name = next((lit for lit in lits if lit != TD_DEF_CMD), '')
            if name in targets:
                out.setdefault(name, []).append(list(staged))
            staged = []
    return out


def gint_let_sites(ff, cmd, ncmd: int, kcc, arg, expr, owners, words: frozenset[int],
                   let_code: int, slot: int, fields: frozenset[int]
                   ) -> dict[int, list[tuple[int, int, int, int, bool]]]:
    """Where a script assigns ``@gInt1144(slot, field)`` for a field in *fields*.

    The fields this is for are the text spacing (see :data:`LET_CMD`), and the
    only place they are set is a plain ``LET`` of a constant: the first argument
    names the variable, the second is the value.  Returns ``field -> [(offset,
    opcode, width, value, negative), ...]`` with the offset into the expression
    block, so a caller can rewrite that constant where it sits.

    ``-2`` is stored as the constant ``2`` plus an :data:`INS_NEG` instruction -
    the sign is a byte of its own, not a bit of the operand - and a value built
    from more than one ``Ins`` (``256*80/100``) is skipped: only a value that
    *is* a single operand can be replaced without changing what the expression
    evaluates to.
    """
    out: dict[int, list[tuple[int, int, int, int, bool]]] = {}
    keep = set(owners)
    for _i, code, first, count in command_records(cmd, ncmd, kcc,
                                                  len(arg) // inj.ARG_SIZE):
        if code != let_code or count != 2 or first not in keep:
            continue
        _lits, target = record_items(ff, arg, expr, first, words)
        if len(target) < 2 or target[-2][3] != slot or target[-1][3] not in fields:
            continue
        if first + 1 not in keep:
            continue
        _kid, _typ, _aop, siz, off = struct.unpack_from(
            inj.ARG_FMT, arg, inj.ARG_SIZE * (first + 1))
        if off + siz > len(expr):
            raise ValueError(f'argument record {first + 1} points outside the '
                             f'expression block')
        ins = list(ins_records(ff, bytes(expr[off:off + siz])))
        if not 1 <= len(ins) <= 2 or ins[0][0] not in INS_INT_WIDTHS:
            continue
        if len(ins) == 2 and ins[1][0] != INS_NEG:
            continue
        icode, start, end, raw = ins[0]
        out.setdefault(target[-1][3], []).append(
            (off + start, icode, end - start,
             int.from_bytes(raw, 'little', signed=True), len(ins) == 2))
    return out


def dialog_records(ff, cmd, ncmd: int, kcc, nrecords: int, arg, expr,
                   codes: dict[str, int]) -> tuple[frozenset[int], int, int]:
    """Record indices whose literals an OS dialog box shows.

    Returns ``(records, n_dialog_calls, n_gosub_calls)``.  A ``DIALOG`` shows every
    argument it is given; a ``GOSUB`` shows them when it jumps to one of the
    wrappers in :data:`UI_GOSUB_LABELS`, whose first argument is the label - which
    is why the label is compared as bytes, the way the engine compares it.
    """
    dialog_code = codes.get(UI_CMD)
    gosub_code = codes.get(UI_GOSUB_CMD)
    records: set[int] = set()
    n_dialog = n_gosub = 0
    for _i, code, first, count in command_records(cmd, ncmd, kcc, nrecords):
        if code == dialog_code and count:
            records.update(range(first, first + count))
            n_dialog += 1
        elif code == gosub_code and count:
            if set(record_literals(ff, arg, expr, first)) & UI_GOSUB_LABEL_BYTES:
                records.update(range(first, first + count))
                n_gosub += 1
    return frozenset(records), n_dialog, n_gosub


def transcode_script(raw: bytes, ff, key: int, kcc, *, src: str = 'cp932',
                     encoding: str = 'gbk',
                     keep_shared: frozenset[bytes] = frozenset(),
                     keep_ui: frozenset[bytes] = frozenset(),
                     labels: frozenset[str] = frozenset(),
                     codes: dict[str, int] | None = None,
                     ui_all: bool = False,
                     face: bytes = b'',
                     td_size: dict[str, int] | None = None,
                     space: dict[int, int] | None = None
                     ) -> tuple[bytes | None, Stats]:
    """Re-encode every string literal of one YSTB script.

    ``codes`` maps command names to their opcodes (``{}`` means "do not look for
    dialog literals"); ``keep_ui`` holds literals that reach a dialog through a
    variable, ``ui_all`` marks a script whose literals are all dialog text, and
    ``labels`` holds the label names of ``ysl.ybn`` (see
    :func:`collect_label_names`) so a literal that names one is left in CP932.
    ``face`` is the NUL padded face name every ``FACE_SOURCE`` literal is
    replaced with (``b''`` leaves them alone); ``td_size`` maps a text definition
    name to the size its ``es.TD.SIZE.SET`` operands have to hold (``None`` leaves
    them alone, and a script that does not define that name is left alone as
    well).  ``space`` maps a ``@gInt1144(FONT_SLOT, field)`` field - one of
    :data:`CHAR_SPACE_FIELD` and :data:`LINE_SPACE_FIELD` - to the value its
    ``LET`` has to hold (``None`` leaves the spacing alone).

    Returns ``(new_bytes, stats)``; ``new_bytes`` is ``None`` when the file is
    already fully re-encoded and nothing was written.
    """
    _ver, ncmd, (cmd, arg, expr, lnos) = inj.read_blocks(raw, ff, key)
    o_cmd, o_arg, o_expr, o_lnos = bytes(cmd), bytes(arg), bytes(expr), bytes(lnos)
    owners, words, _dummies = inj.walk_layout(cmd, ncmd, kcc, len(arg) // inj.ARG_SIZE)

    stats = Stats()
    ui_records: frozenset[int] = frozenset()
    if codes:
        ui_records, stats.dialogs, stats.gosubs = dialog_records(
            ff, cmd, ncmd, kcc, len(arg) // inj.ARG_SIZE, o_arg, o_expr, codes)
    new_expr = bytearray(expr)
    edits: list[tuple[int, int, bytes]] = []
    for j in owners:
        kid, typ, aop, siz, off = struct.unpack_from(inj.ARG_FMT, arg, inj.ARG_SIZE * j)
        if off + siz > len(expr):
            raise ValueError(f'argument record {j} points outside the expression block')
        payload = o_expr[off:off + siz]
        # A ``WORD`` payload *is* the string; anything else is an expression and
        # only its ``str`` instructions hold text.
        ranges = [(0, siz)] if j in words else literal_ranges(ff, payload)
        for start, end in ranges:
            data = payload[start:end]
            if not data or all(b < 0x80 for b in data):
                continue                     # plain ASCII, nothing to re-encode
            stats.literals += 1
            # The stored payload keeps its surrounding quotes; resource names are
            # matched without them.
            bare = strip_quotes(data)
            # Which rule keeps a literal is a decision; whether a hand-written
            # exception still matches anything is a different question, so the
            # prose list is ticked off before any rule can take the literal away.
            if is_prose(data):
                stats.prose.add(literal_text(data))
            if face and bare == FACE_SOURCE_BYTES:
                # A face name is not text: the engine gives these bytes to GDI.
                # Keep the quotes, pad the shorter name back to the same length
                # and let the file layout - and every offset in it - stay put.
                quotes = len(data) - len(bare)
                blob = data[:quotes // 2] + face + data[len(data) - quotes // 2:]
                new_expr[off + start:off + end] = blob
                edits.append((off + start, off + end, blob))
                stats.faces += 1
                stats.changed += 1
                continue
            if bare in keep_shared:
                stats.kept.append(('a scenario script uses it',
                                   bare.decode(src, 'replace')))
                continue
            # A ``GOSUB`` names its target with a string and the engine resolves
            # that string against the label table, which still spells every name
            # in Shift-JIS - so the reference has to stay in Shift-JIS too.  This
            # is compared as *text* on purpose: a re-encoded reference decodes as
            # CP932 with replacement characters and therefore can not match, and
            # the Windows CP936 table and Python's 'gbk' disagree on a few
            # characters, so byte equality would be the wrong question anyway.
            text = literal_text(data)
            if text in labels:
                stats.kept.append((WHY_LABEL, text))
                continue
            # A dialog box is drawn by the operating system, not by the engine, so
            # its bytes are read with the process code page rather than the font's
            # - see the module docstring.
            if ui_all or j in ui_records:
                stats.kept.append((WHY_UI_CMD, bare.decode(src, 'replace')))
                continue
            if bare in keep_ui:
                stats.kept.append((WHY_UI_LITERAL, bare.decode(src, 'replace')))
                continue
            try:
                data.decode(src)             # still a CP932 literal?
            except UnicodeDecodeError:
                if decodes_as_gbk(data):
                    continue    # already re-encoded - nothing for this pass to do
                stats.left.append((data.decode(src, 'replace'),
                                   'not a valid CP932 string'))
                continue
            if is_resource_like(data):
                stats.kept.append(('path-like literal',
                                   bare.decode(src, 'replace')))
                continue
            try:
                blob, hits = transcode_literal(data, src, encoding=encoding)
            except (UnicodeEncodeError, ValueError) as e:
                stats.left.append((data.decode(src, 'replace'),
                                   f'{type(e).__name__}: {e}'))
                continue
            for ch, n in hits.items():
                stats.note_sub(ch, n)
            if blob == data:
                continue
            new_expr[off + start:off + end] = blob
            edits.append((off + start, off + end, blob))
            stats.changed += 1

    # A text size is not a string but an integer operand, and it is the *only*
    # other kind of byte this pass writes.  A script that does not define the
    # name is not an error here - the caller proves up front that some script
    # does (see ``main``), so a name a script does not know is simply not its
    # business.
    if td_size:
        for name, want in td_size.items():
            for commit in td_size_sites(
                    ff, cmd, ncmd, kcc, o_arg, o_expr, owners, words,
                    frozenset((name,))).get(name, ()):
                if len(commit) != 2:
                    raise ValueError(f'{name!r}: its {TD_SIZE_CMD} has '
                                     f'{len(commit)} operand(s), not the width and '
                                     f'the height')
                for (site, _code, width, value), target in zip(commit, want):
                    if value == target:
                        continue
                    if not 0 <= target < 1 << (8 * width - 1):
                        raise ValueError(f'{name!r}: the text size {target} does not fit '
                                         f'in the {width} byte operand at 0x{site:x}')
                    blob = target.to_bytes(width, 'little')
                    new_expr[site:site + width] = blob
                    edits.append((site, site + width, blob))
                    stats.td_sizes.append(f'{name} {value} -> {target}')

    # The two spacing fields are integers as well, but a ``LET`` writes them
    # rather than a text definition - and the constant is the whole value
    # expression there, so the sign it carries is part of the file layout.
    if space:
        let_code = (codes or {}).get(LET_CMD)
        if let_code is None:
            raise ValueError(f'{LET_CMD!r} is not one of this engine commands, so '
                             f'the text spacing can not be found')
        for field, want in space.items():
            for site, _code, width, value, negative in gint_let_sites(
                    ff, cmd, ncmd, kcc, o_arg, o_expr, owners, words, let_code,
                    FONT_SLOT, frozenset((field,))).get(field, ()):
                if negative:
                    value = -value
                if value == want:
                    continue
                if (want < 0) != negative:
                    raise ValueError(
                        f'gInt1144({FONT_SLOT},{field}) holds '
                        f'{"a negative" if negative else "a non-negative"} '
                        f'constant at 0x{site:x}: the sign is an instruction of '
                        f'its own, so {want} can not be written there without '
                        f'moving bytes')
                if abs(want) >= 1 << (8 * width - 1):
                    raise ValueError(f'gInt1144({FONT_SLOT},{field}) = {want}: the '
                                     f'value is stored in a {width} byte operand')
                blob = abs(want).to_bytes(width, 'little')
                new_expr[site:site + width] = blob
                edits.append((site, site + width, blob))
                stats.spaces.append(
                    f'gInt1144({FONT_SLOT},{field}) {value} -> {want}')

    if not edits:
        return None, stats

    # The rewrite must not move a single byte outside the literals it replaces.
    expected = bytearray(o_expr)
    for start, end, blob in edits:
        expected[start:end] = blob
    if bytes(expected) != bytes(new_expr):
        raise ValueError('internal error: a byte outside the string literals changed')

    head = bytearray(raw[:32])
    for block in (cmd, arg, new_expr, lnos):
        ff.xor_trans(block, key)
    new = bytes(head + cmd + arg + new_expr + lnos)
    if len(new) != len(raw):
        raise ValueError(f'the script changed size ({len(raw)} -> {len(new)})')

    # Read the result back and prove what the header promises: same length,
    # untouched blocks, and the new literals exactly where they were.
    _v, _n, (n_cmd, n_arg, n_expr, n_lnos) = inj.read_blocks(new, ff, key)
    if (bytes(n_cmd), bytes(n_arg), bytes(n_lnos)) != (o_cmd, o_arg, o_lnos):
        raise ValueError('verification failed: a command or branch block changed')
    if bytes(n_expr) != bytes(expected):
        raise ValueError('verification failed: the expression block is not what '
                         'was intended')
    if td_size:
        after = td_size_sites(ff, n_cmd, ncmd, kcc, n_arg, n_expr, owners, words,
                              frozenset(td_size))
        for name, want in td_size.items():
            for commit in after.get(name, ()):
                for (_site, _code, _width, value), target in zip(commit, want):
                    if value != target:
                        raise ValueError(f'verification failed: the text definition '
                                         f'{name!r} reads the size {value}, not {target}')
    if space:
        after = gint_let_sites(ff, n_cmd, ncmd, kcc, n_arg, n_expr, owners, words,
                               (codes or {}).get(LET_CMD), FONT_SLOT,
                               frozenset(space))
        for field, want in space.items():
            for _site, _code, _width, value, negative in after.get(field, ()):
                if (-value if negative else value) != want:
                    raise ValueError(f'verification failed: '
                                     f'gInt1144({FONT_SLOT},{field}) reads the '
                                     f'spacing {value}, not {want}')
    return new, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Re-encode the engine scripts of a YU-RIS game from CP932 '
                    'into GBK (same length, in place).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example: python transcode_yuris_scripts.py --indir D:\\ysbin '
               '--outdir build\\ysbin')
    ap.add_argument('--indir', default=r'D:\ysbin',
                    help='folder holding the original scripts (default: D:\\ysbin)')
    ap.add_argument('--outdir', required=True,
                    help='folder to write the re-encoded scripts into '
                         '(an overlay: only files that change are written)')
    ap.add_argument('--repo', default=None,
                    help='path to the yuris_decompiler checkout')
    ap.add_argument('--key', default='auto',
                    help='YSTB XOR key such as 0x801DD23F, or "auto" (default)')
    ap.add_argument('--source-encoding', default='cp932',
                    help='encoding of the original text (default: cp932)')
    ap.add_argument('--encoding', default='gbk',
                    help='encoding to write (default: gbk; the engine is code '
                         'page 936, other values are not supported)')
    ap.add_argument('--min-idx', type=int, default=0,
                    help='lowest script index to convert (default: 0)')
    ap.add_argument('--max-idx', type=int, default=DEFAULT_MAX_IDX,
                    help=f'highest script index to convert '
                         f'(default: {DEFAULT_MAX_IDX} - the userscript scripts '
                         f'are rebuilt by inject_yuris_text.py instead)')
    ap.add_argument('--face', default=FACE_TARGET,
                    help=f'face name every "{FACE_SOURCE}" literal is replaced '
                         f'with (default: {FACE_TARGET!r}); at most '
                         f'{FACE_BYTES} ASCII bytes, and it must be a font the '
                         f'system actually has (see install_glow_sans.py).  Pass '
                         f'an empty string to leave the literals alone')
    ap.add_argument('--td-size', default='', metavar='NAME=WxH',
                    help='resize the named text definitions of '
                         'userdefine\\文字定義.txt, as NAME=SIZE pairs separated '
                         'by commas or spaces (e.g. "M=30x38"): "M" is the '
                         'dialogue the ADV screen draws, "NAME" the speaker plate, '
                         'and every menu and system definition keeps its size.  '
                         'A size is the character cell in pixels - one number for '
                         'a square cell, or WIDTHxHEIGHT for the pen advance and '
                         'the glyph height separately (a wide face with large ink '
                         'wants a narrower cell than it is tall).  The operands '
                         'are one byte each, so nothing else in the file moves')
    ap.add_argument('--char-space', type=int, default=None, metavar='PIXELS',
                    help='pixels the renderer adds between two characters '
                         '(gInt1144(36,19), the letter spacing).  A negative '
                         'value tightens the text; the game ships -2, and a wide '
                         'face that leaves gaps needs maybe -6.  The sign of the '
                         'stored constant can not be flipped')
    ap.add_argument('--line-space', type=int, default=None, metavar='PIXELS',
                    help='pixels the renderer adds between two lines '
                         '(gInt1144(36,20), the line spacing); the game ships 0')
    ap.add_argument('--report', default=None,
                    help='write a TSV report of what was converted')
    ap.add_argument('--i-encoding', default='cp932',
                    help='encoding of the *original* scripts, for the key '
                         'detection (default: cp932)')
    ap.add_argument('--verbose', action='store_true',
                    help='let the key detection print its score board')
    args = ap.parse_args(argv)

    if args.encoding.lower() not in CP936_ALIASES:
        print(f'error: --encoding {args.encoding!r} is not supported: the engine '
              f'reads code page 936', file=sys.stderr)
        return 2
    try:
        face = face_literal(args.face) if args.face else b''
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    try:
        td_size = parse_td_sizes(args.td_size)
    except ValueError as e:
        print(f'error: --td-size: {e}', file=sys.stderr)
        return 2

    ff, kcc, key, indir, files, paths = inj.load_game(args)
    outdir = Path(args.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)

    # The dialog keep rules need the opcode of the two commands they look for.
    with open(indir / 'ysc.ybn', 'rb') as fp:
        codes = {c.name: i for i, c in
                 enumerate(ff.YSCM(ff.Rdr(fp.read(), enc=args.i_encoding)).cmds)}
    for name in (UI_CMD, UI_GOSUB_CMD):
        if name not in codes:
            inj.warn(f'command {name!r} is not in ysc.ybn - literals an OS dialog '
                     f'box shows can not be recognised')
    keep_ui = frozenset(lit.encode(args.source_encoding) for lit in UI_LITERALS)
    ui_scripts = tuple(frag.lower() for frag in UI_SCRIPTS)

    # A scenario script keeps its CP932 bytes except for the dialogue the pack
    # rewrites, so any literal it shares with an engine script stays CP932 here.
    shared = collect_shared_literals(files, ff, key, kcc, args.max_idx + 1,
                                     args.source_encoding)

    # A ``GOSUB``'s target is resolved against the label table, which this pack
    # does not ship and which therefore still spells the names in Shift-JIS.
    labels = collect_label_names(indir, ff, args.source_encoding)
    nonascii_labels = frozenset(l for l in labels if not l.isascii())

    # A text definition lives in the one script that stages and commits it
    # (``userdefine\文字定義.txt`` for the definitions the ADV screen draws
    # with), so answering "does the name we were asked to resize exist at all?"
    # before anything is written turns a typo into a failed build rather than a
    # pack that quietly keeps the old size.
    td_scripts: dict[str, list[str]] = {}
    td_operands: dict[str, int] = {}
    td_widths: dict[str, int] = {}
    if td_size:
        for p in files:
            idx = inj.script_index(p.name)
            if not idx or not (args.min_idx <= int(idx) <= args.max_idx):
                continue
            try:
                _v, ncmd, (cmd, arg, expr, _l) = inj.read_blocks(p.read_bytes(),
                                                                 ff, key)
                owners, words, _d = inj.walk_layout(cmd, ncmd, kcc,
                                                    len(arg) // inj.ARG_SIZE)
                sites = td_size_sites(ff, cmd, ncmd, kcc, arg, expr, owners,
                                      words, frozenset(td_size))
            except Exception as e:
                inj.warn(f'{p.name}: {type(e).__name__}: {e}')
                continue
            for name, commits in sites.items():
                td_scripts.setdefault(name, []).append(p.name)
                td_operands[name] = (td_operands.get(name, 0)
                                     + sum(len(c) for c in commits))
                td_widths[name] = max(td_widths.get(name, 0), max(
                    width for c in commits for _o, _c, width, _v in c))
        missing = [name for name in sorted(td_size) if not td_operands.get(name)]
        if missing:
            print('error: no script defines a text definition named '
                  + ', '.join(repr(m) for m in missing)
                  + ' - there is nothing to resize', file=sys.stderr)
            return 2
        # An out of range value would abort that one script in the loop below and
        # the pack would keep the old size, so it has to stop the build here.
        for name in sorted(td_size):
            width = td_widths[name]
            for part in td_size[name]:
                if not 0 <= part < 1 << (8 * width - 1):
                    print(f'error: --td-size {name}={part}: the text '
                          f'definition {name!r} keeps its size in a {width} byte '
                          f'operand, so it has to be 1..{(1 << (8 * width - 1)) - 1} '
                          f'({", ".join(td_scripts[name])})', file=sys.stderr)
                    return 2
        print(f'resizing {len(td_size)} text definition(s):')
        for name in sorted(td_size):
            print(f'    {name} = {td_size[name][0]}x{td_size[name][1]}: '
                  f'{td_operands[name]} {TD_SIZE_CMD} operand(s) in '
                  f'{", ".join(td_scripts[name])}')

    # Same reasoning as the sizes above: the spacing is assigned in a handful of
    # engine scripts, and a field the game never assigns - or assigns with the
    # other sign - can not be retuned from here.
    space: dict[int, int] = {}
    for field, want, flag in ((CHAR_SPACE_FIELD, args.char_space, '--char-space'),
                              (LINE_SPACE_FIELD, args.line_space,
                               '--line-space')):
        if want is None:
            continue
        if not -127 <= want <= 127:
            print(f'error: {flag} {want}: the spacing is one signed byte, so it '
                  f'has to be -127..127', file=sys.stderr)
            return 2
        space[field] = want
    if space:
        sites: dict[int, list[tuple[str, int, bool]]] = {}
        for p in files:
            try:
                _v, ncmd, (cmd, arg, expr, _l) = inj.read_blocks(p.read_bytes(),
                                                                 ff, key)
                owners, words, _d = inj.walk_layout(cmd, ncmd, kcc,
                                                    len(arg) // inj.ARG_SIZE)
                where = gint_let_sites(ff, cmd, ncmd, kcc, arg, expr, owners,
                                       words, codes.get(LET_CMD), FONT_SLOT,
                                       frozenset(space))
            except Exception as e:
                inj.warn(f'{p.name}: {type(e).__name__}: {e}')
                continue
            for field, entries in where.items():
                sites.setdefault(field, []).extend(
                    (p.name, value, negative) for _o, _c, _w, value, negative
                    in entries)
        lines: list[str] = []
        for field in sorted(space):
            what = 'letter' if field == CHAR_SPACE_FIELD else 'line'
            flag = ('--char-space' if field == CHAR_SPACE_FIELD
                    else '--line-space')
            entries = sites.get(field, [])
            if not entries:
                print(f'error: no script assigns gInt1144({FONT_SLOT},{field}), '
                      f'the {what} spacing - there is nothing for {flag} to '
                      f'change', file=sys.stderr)
                return 2
            negative = entries[0][2]
            if any(entry[2] != negative for entry in entries):
                print(f'error: gInt1144({FONT_SLOT},{field}) is assigned with '
                      f'both signs across the engine scripts, so {flag} can not '
                      f'mean the same thing everywhere', file=sys.stderr)
                return 2
            if (space[field] < 0) != negative:
                print(f'error: gInt1144({FONT_SLOT},{field}) holds a '
                      f'{"negative" if negative else "non-negative"} constant: '
                      f'the sign is an instruction of its own, so {space[field]} '
                      f'can not be written there without moving bytes',
                      file=sys.stderr)
                return 2
            held = {value for _n, value, _neg in entries}
            lines.append(f'    gInt1144({FONT_SLOT},{field}) = {space[field]}: '
                         f'the {what} spacing, {len(entries)} assignment(s) '
                         f'holding '
                         + '/'.join(str(abs(v)) for v in sorted(held, key=abs))
                         + ' in '
                         + ', '.join(sorted({n for n, _v, _g in entries})))
        print('retuning the text spacing:')
        for line in lines:
            print(line)

    report: list[tuple[str, ...]] = []
    changed = same = failed = 0
    n_lit = n_changed = 0
    n_dialog = n_gosub = 0
    subs: dict[str, int] = {}
    left: dict[str, tuple[str, str]] = {}          # literal -> (script, reason)
    kept: dict[str, tuple[str, str]] = {}          # literal -> (script, reason)
    kept_reasons: dict[str, int] = {}              # reason -> how often it fired
    prose_seen: set[str] = set()
    ui_scripts_seen: set[str] = set()
    face_sites: dict[str, int] = {}                # script -> renamed literals
    td_changes: dict[str, list[str]] = {}          # script -> text sizes rewritten
    space_changes: dict[str, list[str]] = {}       # script -> text spacing rewritten
    for p in files:
        idx = inj.script_index(p.name)
        if not idx or not (args.min_idx <= int(idx) <= args.max_idx):
            continue
        path = paths.get(int(idx), '').lower()
        ui_all = any(frag in path for frag in ui_scripts)
        ui_scripts_seen |= {frag for frag in ui_scripts if frag in path}
        raw = p.read_bytes()
        try:
            new, stats = transcode_script(
                raw, ff, key, kcc, src=args.source_encoding,
                encoding=args.encoding,
                keep_shared=shared, keep_ui=keep_ui, labels=labels,
                codes=codes, ui_all=ui_all,
                face=face, td_size=td_size, space=space)
        except Exception as e:
            failed += 1
            inj.warn(f'{p.name}: {type(e).__name__}: {e}')
            report.append((p.name, idx, str(len(raw)), '', '', '', '',
                           f'skipped: {type(e).__name__}'))
            continue

        n_lit += stats.literals
        n_changed += stats.changed
        n_dialog += stats.dialogs
        n_gosub += stats.gosubs
        for ch, n in stats.subs.items():
            subs[ch] = subs.get(ch, 0) + n
        for lit, why in stats.left:
            left.setdefault(lit, (p.name, why))
        for reason, lit in stats.kept:
            kept.setdefault(lit, (p.name, reason))
            kept_reasons[reason] = kept_reasons.get(reason, 0) + 1
        prose_seen |= stats.prose
        if stats.faces:
            face_sites[p.name] = stats.faces
        if stats.td_sizes:
            td_changes[p.name] = stats.td_sizes
        if stats.spaces:
            space_changes[p.name] = stats.spaces
        if new is None:
            same += 1
        else:
            (outdir / p.name).write_bytes(new)
            changed += 1
        report.append((p.name, idx, str(len(raw)), str(stats.literals),
                       str(stats.changed), str(len(stats.kept)),
                       str(len(stats.left)),
                       'unchanged' if new is None else 'written'))
    print(f'{changed} script(s) re-encoded, {same} unchanged, {failed} skipped; '
          f'{n_changed} of {n_lit} string(s) re-encoded')
    if shared:
        print(f'    {len(shared)} literal(s) are also used by a scenario script')
    if args.face:
        n_faces = sum(face_sites.values())
        print(f'    {n_faces} face-name literal(s) renamed to {args.face!r} '
              f'({len(face_sites)} script(s))')
        for name, n in sorted(face_sites.items()):
            print(f'      {name}: {n}')
    if td_size:
        n_td = sum(len(v) for v in td_changes.values())
        if n_td:
            print(f'    {n_td} text size operand(s) rewritten:')
            for name in sorted(td_changes):
                for item in td_changes[name]:
                    print(f'      {name}: {item}')
        else:
            print('    every text size operand already holds the size asked for')
    if space:
        n_space = sum(len(v) for v in space_changes.values())
        if n_space:
            print(f'    {n_space} text spacing operand(s) rewritten:')
            for name in sorted(space_changes):
                for item in space_changes[name]:
                    print(f'      {name}: {item}')
        else:
            print('    every spacing operand already holds the value asked for')
    if codes:
        print(f'    {n_dialog} DIALOG command(s) and {n_gosub} GOSUB call(s) into a '
              f'dialog wrapper hold text the OS shows')
    if kept:
        print(f'    {len(kept)} literal(s) stay in CP932 on purpose:')
        for reason, n in sorted(kept_reasons.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'      {n:6d}  {reason}')
    for ch, n in sorted(subs.items(), key=lambda kv: -kv[1]):
        print(f'    substituted {ch} (U+{ord(ch):04X}) -> '
              f'{tg.SUBSTITUTIONS[ch]}  x{n}')
    if left:
        print(f'    {len(left)} literal(s) could not be re-encoded and stay '
              f'in CP932:')
        for lit, (name, why) in sorted(left.items())[:15]:
            print(f'      {name}: {lit[:40]!r} - {why}')
        if len(left) > 15:
            print(f'      ... and {len(left) - 15} more')

    # The prose exception list and the dialog script list are hand-written, so a
    # typo in either must not pass silently - but only a run over the whole engine
    # range can judge them, and the caption rule only ever fires there.
    if args.min_idx == 0 and args.max_idx >= DEFAULT_MAX_IDX:
        if args.face and not face_sites:
            inj.warn(f'no {FACE_SOURCE!r} literal was found in any script - the '
                     f'pack would name a face nowhere, or the game does not use '
                     f'one')
        for lit in sorted(DISPLAY_CP932 - prose_seen):
            inj.warn('prose exception never matched a literal - out of date? '
                     f'{lit!r}')
        for frag in UI_SCRIPTS:
            if frag.lower() not in ui_scripts_seen:
                inj.warn(f'dialog script {frag!r} matched no script path - out '
                         f'of date?')
        for lit in sorted(UI_LITERALS):
            if lit not in kept:
                inj.warn(f'dialog caption {lit!r} is not in any script any more - '
                         f'is the rule still needed?')
        if nonascii_labels and WHY_LABEL not in kept_reasons:
            inj.warn(f'{len(nonascii_labels)} label name(s) in ysl.ybn are not '
                     f'ASCII but no script names one - is the label rule still '
                     f'needed?')

    if args.report:
        out = Path(args.report).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        header = ('script_file', 'script_idx', 'bytes', 'literals', 'changed',
                  'kept', 'left', 'status')
        with open(out, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('\t'.join(header) + '\r\n')
            for row in report:
                f.write('\t'.join(row) + '\r\n')
            for lit, (name, why) in sorted(left.items()):
                f.write('\t'.join(('!left-cp932', name, '', '', '', '', '',
                                   f'{lit} - {why}')) + '\r\n')
            for lit, (name, reason) in sorted(kept.items()):
                f.write('\t'.join(('!kept-cp932', name, '', '', '', '', '',
                                   f'{lit} - {reason}')) + '\r\n')
            for name in sorted(td_changes):
                for item in td_changes[name]:
                    f.write('\t'.join(('!td-size', name, '', '', '', '', '',
                                       item)) + '\r\n')
            for name in sorted(space_changes):
                for item in space_changes[name]:
                    f.write('\t'.join(('!td-space', name, '', '', '', '', '',
                                       item)) + '\r\n')
        print(f'wrote {out}')

    if failed:
        print('error: some scripts could not be converted - they keep their '
              'CP932 bytes', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
