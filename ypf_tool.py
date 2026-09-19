#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read, verify and build YU-RIS ``.ypf`` resource archives (version 500).

Layout of a version 500 archive::

    offset 0   0x00  'YPF\\0'               u32
               0x04  version              u32
               0x08  entry count          u32
               0x0c  header size          u32   (32 + the whole entry table)
               0x10  16 zero bytes
    header     0x20  the entry table
    data             the stored blobs, in table order

Each entry is ``<IB`` - the murmurhash2 of the plain name plus the obfuscated
name length - followed by that many obfuscated name bytes, then
``<BBIIQI`` = ``kind, compressed, unpacked size, stored size, offset, hash``.
``hash`` is the murmurhash2 of the *stored* blob, so a compressed entry hashes
its compressed bytes.  Names are decoded as CP932 and are Windows relative
paths such as ``ysbin\\yst00182.ybn``.  Every stored blob is followed by four
zero bytes, which the engine ignores and which this tool reproduces so that a
rebuilt archive looks like the one the game shipped.

Two facts drive the design:

* the byte level output of the original packer can not be reproduced, because
  it used the zlib 1.2.3 that ships as ``YSZLB.DLL`` and modern zlib picks
  different (equally valid) matches at level 9;
* therefore ``repack`` copies every unchanged entry's stored blob **verbatim**
  and only recompresses the entries you actually modified.

``hash`` is the only integrity field the format has, and the engine can compute
it (murmurhash2 is implemented in the exe), so this tool always recomputes both
hashes on write; ``check`` verifies them on read.  The engine itself has no
SHA-256 / SHA-1 / MD5 capability and imports no crypto API - a SHA-256 compare
anywhere in this project is our own file identity check, not a gate the game
enforces (see STYLE_GUIDE 2.4).

The name obfuscation tables and the hash functions are the ones in the
``yuris_decompiler`` reader (``yurislib/fileformat.py``, lines 46-63), copied
here so this tool stands on its own (upstream is MIT - see NOTICE.md §1);
``--selftest`` checks them against it.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

MAGIC = 0x00465059                     # 'YPF\0' read little endian
NAME_ENCODING = 'cp932'

NLSwaps = ((6, 53), (9, 11), (12, 16), (13, 19), (21, 27),
           (28, 30), (32, 35), (38, 41), (44, 47))


def _swap_trans(*pairs: tuple[int, int]) -> bytes:
    bs = bytearray(range(256))
    for i, j in pairs:
        assert bs[i] == i and bs[j] == j, 'overlapping swaps'
        bs[i], bs[j] = bs[j], bs[i]
    return bytes(bs)


NLTransV000 = _swap_trans((3, 72), (17, 25), (46, 50), *NLSwaps)
NLTransV500 = _swap_trans((3, 10), (17, 24), (20, 46), *NLSwaps)
NameXorV000 = bytes(i ^ 0xff for i in range(256))
NameXorV290 = bytes(c ^ 0x40 for c in NameXorV000)
NameXorV500 = bytes(c ^ 0x36 for c in NameXorV000)
ENTRY_FMT_V000 = '<BBIIII'             # 18 bytes, 32 bit offset
ENTRY_FMT_V470 = '<BBIIQI'             # 22 bytes, 64 bit offset
PAD = b'\0' * 4                        # written after every stored blob

try:
    from murmurhash2 import murmurhash2 as _murmurhash2
except ImportError:  # pragma: no cover
    print('error: the murmurhash2 package is required (pip install murmurhash2)',
          file=sys.stderr)
    raise SystemExit(1)


def mmh2(data: bytes) -> int:
    return _murmurhash2(data, 0) & 0xFFFFFFFF


def error(msg: str) -> None:
    print(f'error: {msg}', file=sys.stderr)


def table_layout(ver: int) -> tuple[bytes, bytes, str, int]:
    """Return ``(name_size_trans, name_byte_trans, entry_fmt, entry_size)``."""
    if ver == 500:
        nb = NameXorV500
    elif ver == 290:
        nb = NameXorV290
    else:
        nb = NameXorV000
    return (NLTransV500 if ver == 500 else NLTransV000, nb,
            ENTRY_FMT_V470 if ver >= 470 else ENTRY_FMT_V000,
            struct.calcsize(ENTRY_FMT_V470 if ver >= 470 else ENTRY_FMT_V000))


def data_start(ver: int, lhdr: int) -> int:
    return lhdr if ver >= 300 else lhdr + 32


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #

def read_ypf(src: Path | bytes, *, names: bool = True,
             check: bool = True) -> tuple[int, list[dict]]:
    """Parse an archive into ``(version, entries)``.

    Each entry is ``{name, raw, blob, comp, ul, off}`` - ``raw`` is the usable
    content and ``blob`` the exact bytes stored in the file.
    """
    buf = src if isinstance(src, bytes) else Path(src).read_bytes()
    if len(buf) < 32:
        raise ValueError('file is too short to be a ypf archive')
    magic, ver, nent, lhdr = struct.unpack_from('<4I', buf, 0)
    if magic != MAGIC:
        raise ValueError(f'bad magic {magic:08X}, expected {MAGIC:08X}')
    if any(buf[16:32]):
        raise ValueError('the 16 header padding bytes are not zero')
    nl_trans, nb_trans, ent_fmt, ent_size = table_layout(ver)
    if not (200 <= ver < 501):
        raise ValueError(f'unsupported ypf version {ver}')

    off = 32
    entries = []
    for i in range(nent):
        if off + 5 > len(buf):
            raise ValueError(f'entry {i}: truncated name header')
        name_hash, name_size = struct.unpack_from('<IB', buf, off)
        off += 5
        n = nl_trans[name_size ^ 0xff]
        stored_name = bytes(buf[off:off + n])
        if len(stored_name) != n:
            raise ValueError(f'entry {i}: truncated name')
        off += n
        name_bytes = stored_name.translate(nb_trans)
        if check and mmh2(name_bytes) != name_hash:
            raise ValueError(f'entry {i}: name hash mismatch '
                             f'(stored {name_hash:08X}, computed {mmh2(name_bytes):08X})')
        if off + ent_size > len(buf):
            raise ValueError(f'entry {i}: truncated entry record')
        kind, comp, ul, cl, offset, fhash = struct.unpack_from(ent_fmt, buf, off)
        off += ent_size
        blob = bytes(buf[offset:offset + cl])
        if len(blob) != cl:
            raise ValueError(f'entry {i}: stored blob runs past the end of the file')
        if check and mmh2(blob) != fhash:
            raise ValueError(f'entry {i}: file hash mismatch '
                             f'(stored {fhash:08X}, computed {mmh2(blob):08X})')
        if comp:
            raw = zlib.decompress(blob)
            if check and len(raw) != ul:
                raise ValueError(f'entry {i}: unpacked size {len(raw)}, header says {ul}')
        else:
            raw = blob
        entries.append({
            'name': name_bytes.decode(NAME_ENCODING) if names else name_bytes.decode(
                NAME_ENCODING, 'replace'),
            'raw': raw,
            'blob': blob,
            'comp': comp,
            'ul': len(raw),
            'off': offset,
        })
    want = data_start(ver, lhdr)
    if off != want:
        raise ValueError(f'entry table ends at {off}, header says {want}')
    return ver, entries


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #

def build(entries: list[dict], ver: int = 500, *, dedup: bool = True,
          level: int = 9) -> bytes:
    """Serialise *entries* into an archive.

    ``entries`` is a list of ``{'name', 'raw'}``.  An entry may additionally
    carry ``{'blob', 'comp', 'ul'}`` to have its stored bytes copied verbatim
    instead of being recompressed, which is how ``repack`` keeps every file it
    did not touch byte identical.
    """
    if not (200 <= ver < 501):
        raise ValueError(f'unsupported ypf version {ver}')
    nl_trans, nb_trans, ent_fmt, ent_size = table_layout(ver)

    inv_size = bytearray(256)
    for s in range(256):
        inv_size[nl_trans[s ^ 0xff]] = s
    inv_byte = bytearray(256)
    for s in range(256):
        inv_byte[nb_trans[s]] = s

    prepared = []
    for e in entries:
        name_bytes = e['name'].encode(NAME_ENCODING)
        if not name_bytes or len(name_bytes) > 255:
            raise ValueError(f'name {e["name"]!r} does not fit the format')
        raw = e['raw']
        if 'blob' in e:
            blob, comp, ul = e['blob'], e['comp'], e['ul']
        else:
            packed = zlib.compress(raw, level)
            if len(packed) >= len(raw):
                blob, comp, ul = raw, 0, len(raw)
            else:
                blob, comp, ul = packed, 1, len(raw)
        prepared.append({'name': name_bytes, 'raw': raw, 'blob': blob,
                         'comp': comp, 'ul': ul, 'share': None})

    if dedup:
        seen: dict[tuple, dict] = {}
        for p in prepared:
            key = (p['blob'], p['comp'], p['ul'])
            if key in seen:
                p['share'] = seen[key]
            else:
                seen[key] = p

    lhdr = 32
    for p in prepared:
        lhdr += 5 + len(p['name']) + ent_size

    cur = data_start(ver, lhdr)
    for p in prepared:
        if p['share'] is None:
            p['off'] = cur
            cur += len(p['blob']) + len(PAD)
        else:
            p['off'] = p['share']['off']
    total = cur

    out = bytearray()
    out += struct.pack('<4I', MAGIC, ver, len(prepared), lhdr)
    out += bytes(16)
    for p in prepared:
        out += struct.pack('<IB', mmh2(p['name']), inv_size[len(p['name'])])
        out += p['name'].translate(inv_byte)
        out += struct.pack(ent_fmt, 0, p['comp'], p['ul'], len(p['blob']),
                           p['off'], mmh2(p['blob']))
    assert len(out) == lhdr, f'table is {len(out)} bytes, header says {lhdr}'
    for p in prepared:
        if p['share'] is None:
            assert len(out) == p['off']
            out += p['blob']
            out += PAD
    assert len(out) == total, f'archive is {len(out)} bytes, planned {total}'
    return bytes(out)


def find_local(name: str, dirs: list[Path]) -> Path | None:
    """Map an archive name onto a file below one of *dirs*.

    ``ysbin\\yst00182.ybn`` is looked up as ``<dir>\\ysbin\\yst00182.ybn`` and,
    if that is missing, as ``<dir>\\yst00182.ybn``, so a flat folder of patched
    scripts works as well as a full tree.
    """
    rel = name.replace('\\', '/').lstrip('/')
    candidates = [rel]
    if '/' in rel:
        candidates.append(rel.split('/', 1)[1])
    for d in dirs:
        for cand in candidates:
            p = d / cand
            if p.is_file():
                return p
    return None


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_list(args) -> int:
    ver, entries = read_ypf(Path(args.ypf))
    print(f'{args.ypf}: version {ver}, {len(entries)} entrie(s)')
    print('    %-44s %10s %10s %5s %s' % ('name', 'stored', 'unpacked', 'comp', 'offset'))
    for e in entries:
        print('    %-44s %10d %10d %5s %d'
              % (e['name'], len(e['blob']), e['ul'],
                 'yes' if e['comp'] else 'no', e['off']))
    return 0


def cmd_extract(args) -> int:
    dst = Path(args.outdir)
    ver, entries = read_ypf(Path(args.ypf))
    for e in entries:
        target = dst / e['name'].replace('\\', '/')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(e['blob'] if args.raw else e['raw'])
    print(f'extracted {len(entries)} entrie(s) from {args.ypf} to {dst} '
          f'(version {ver}{" , stored bytes" if args.raw else ""})')
    return 0


def cmd_verify(args) -> int:
    ver, entries = read_ypf(Path(args.ypf))
    dirs = [Path(d) for d in args.dir]
    same = diff = absent = 0
    for e in entries:
        local = find_local(e['name'], dirs)
        if local is None:
            absent += 1
            continue
        data = local.read_bytes()
        if data == e['raw']:
            same += 1
        else:
            diff += 1
            print(f'  DIFF  {e["name"]}: archive {len(e["raw"])} byte(s), '
                  f'{local} {len(data)} byte(s)')
    print(f'{args.ypf}: version {ver}, {len(entries)} entrie(s)')
    print(f'  {same} identical, {diff} different, {absent} not found below '
          f'{", ".join(str(d) for d in dirs)}')
    return 1 if diff else 0


def cmd_make(args) -> int:
    entries: list[dict] = []
    for spec in args.add or []:
        local, _, name = spec.partition('=')
        if not name:
            name = args.name_prefix + Path(local).name
        entries.append({'name': name.replace('/', '\\'),
                        'raw': Path(local).read_bytes()})
    if args.from_dir:
        root = Path(args.from_dir)
        for p in sorted(root.rglob('*')):
            if p.is_file():
                name = args.name_prefix + str(p.relative_to(root)).replace('/', '\\')
                entries.append({'name': name, 'raw': p.read_bytes()})
    if not entries:
        error('nothing to pack - pass --add <file>[=<archive name>] or --from-dir <folder>')
        return 1
    data = build(entries, args.ver, dedup=False, level=args.level)
    out = Path(args.out)
    if out.parent != Path(''):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    ver, back = read_ypf(data)
    ok = len(back) == len(entries) and all(
        b['name'] == e['name'] and b['raw'] == e['raw']
        for b, e in zip(back, entries))
    print(f'wrote {out} ({len(data)} byte(s), version {ver}, {len(entries)} entrie(s))')
    for e in entries:
        print(f'    {e["name"]}  {len(e["raw"])} byte(s)')
    print('  re-read check:', 'OK' if ok else 'FAILED')
    return 0 if ok else 1


def cmd_repack(args) -> int:
    src = Path(args.base)
    ver, entries = read_ypf(src)
    dirs = [Path(d) for d in args.dir]
    replaced: list[str] = []
    for e in entries:
        local = find_local(e['name'], dirs)
        if local is None:
            continue
        data = local.read_bytes()
        if data == e['raw']:
            continue
        replaced.append(e['name'])
        e['raw'] = data
        for key in ('blob', 'comp', 'ul'):
            e.pop(key, None)

    if not replaced:
        print(f'nothing changed - no file below '
              f'{", ".join(str(d) for d in dirs)} differs from {src.name}')
        return 0

    data = build(entries, ver, dedup=args.dedup, level=args.level)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)

    want = {e['name']: e['raw'] for e in entries}
    _ver2, back = read_ypf(data)
    bad = [b['name'] for b in back if b['raw'] != want.get(b['name'])]
    print(f'{src.name} -> {out}')
    print(f'  {len(entries)} entrie(s), {len(replaced)} replaced, '
          f'{len(data)} byte(s)')
    for name in replaced:
        print(f'    replaced {name}')
    print('  re-read check:', 'OK' if not bad and len(back) == len(entries)
          else f'FAILED for {bad}')
    return 0 if not bad and len(back) == len(entries) else 1


def cmd_selftest(args) -> int:
    """Confirm the copied tables match the reference implementation."""
    repo = (Path(args.repo).expanduser() if args.repo
            else Path(__file__).resolve().parent / 'yuris_decompiler')
    sys.path.insert(0, str(repo))
    import importlib
    ff = importlib.import_module('yurislib.fileformat')
    pairs = [('NLTransV000', NLTransV000, ff.NLTransV000),
             ('NLTransV500', NLTransV500, ff.NLTransV500),
             ('NameXorV290', NameXorV290, ff.NameXorV290),
             ('NameXorV500', NameXorV500, ff.NameXorV500)]
    ok = True
    for name, mine, theirs in pairs:
        match = bytes(mine) == bytes(theirs)
        ok &= match
        print(f'  {name:<12} {"match" if match else "MISMATCH"}')
    for probe in (b'', b'ysbin\\yst00182.ybn', bytes(range(256))):
        match = mmh2(probe) == ff.mmh2(probe, 0) or ff.mmh2(probe, 0) is False
        ok &= match
    print(f'  mmh2         {"match" if ok else "MISMATCH"}')
    print('selftest:', 'OK' if ok else 'FAILED')
    return 0 if ok else 1


# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description='Read, verify and build YU-RIS .ypf resource archives.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  python ypf_tool.py list pac\\bn.ypf\n'
               '  python ypf_tool.py verify pac\\bn.ypf D:\\ysbin\n'
               '  python ypf_tool.py make --from-dir D:\\patch --out update1.ypf\n'
               '  python ypf_tool.py repack --base pac\\bn.ypf --dir D:\\ysbin_cn '
               '--out bn_new.ypf')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('list', help='print the entry table')
    p.add_argument('ypf')
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('extract', help='unpack an archive')
    p.add_argument('ypf')
    p.add_argument('outdir')
    p.add_argument('--raw', action='store_true',
                   help='write the stored bytes instead of the decompressed ones')
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser('verify', help='compare an archive against a folder')
    p.add_argument('ypf')
    p.add_argument('--dir', action='append', required=True,
                   help='folder holding the extracted content (repeatable)')
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('make', help='build a small archive (e.g. update1.ypf)')
    p.add_argument('--out', required=True)
    p.add_argument('--add', action='append', metavar='FILE[=NAME]',
                   help='add one file; the default name is <prefix><basename>')
    p.add_argument('--name-prefix', default='ysbin\\',
                   help='prefix used when --add has no explicit name')
    p.add_argument('--from-dir', default=None,
                   help='add every file below this folder, named by its '
                        'relative path (so the folder must contain ypfsrc/)')
    p.add_argument('--ver', type=int, default=500)
    p.add_argument('--level', type=int, default=9, help='zlib level (default 9)')
    p.set_defaults(func=cmd_make)

    p = sub.add_parser('repack', help='rebuild an archive, replacing changed files')
    p.add_argument('--base', required=True, help='the archive to start from')
    p.add_argument('--dir', action='append', required=True,
                   help='folder with the modified files (repeatable)')
    p.add_argument('--out', required=True)
    p.add_argument('--level', type=int, default=9)
    p.add_argument('--no-dedup', dest='dedup', action='store_false',
                   help='do not share one blob between identical files')
    p.set_defaults(func=cmd_repack, dedup=True)

    p = sub.add_parser('selftest',
                       help='check the built in tables against yuris_decompiler')
    p.add_argument('--repo', default=None)
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError, zlib.error) as e:
        error(f'{type(e).__name__}: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
