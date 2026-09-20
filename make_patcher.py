#!/usr/bin/env python
"""Assemble the A2 patch release: installer + payload + wrappers + docs.

What comes out (``release/<name>/``):

  install_cn_patch.exe      frozen installer (PyInstaller --onedir) + _internal/
  install_cn_patch.py       the same installer as readable source ("source mode")
  requirements.txt          for source mode
  安装汉化.bat / 卸载汉化.bat / 安装汉化-源码版.bat / 说明.txt / NOTICE.md / LICENSE
  payload/                  manifest.json + tools + workpack + font + yurislib

Nothing in here is game data: the payload carries the *translation table* and the
toolchain, and the installer reads the original scripts out of the user's own
``pac\\bn.ypf``.  ``manifest.json`` pins the expected result byte-for-byte, so a
release that would produce something else refuses to install.

Examples::

    python make_patcher.py --manifest-only          # refresh payload/manifest.json
    python make_patcher.py --skip-freeze            # payload + wrappers, no PyInstaller
    python make_patcher.py --zip                    # full release + zip
    python make_patcher.py --version 1.1.0 --zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
DEFAULT_VERSION = "1.0.0"
GAME_EXE = "oujunoshima.exe"
FONT_NAME = "GlowSansSC-Normal-Light.otf"
FONT_FAMILY = "Glow Sans SC"
FONT_WEIGHT = "light"
LINE_METRICS = "typo"
TD_SIZE = "M=30x32, NAME=30x32"
EXE_FONTS = "Glow Sans SC,Microsoft YaHei,SimHei"
EXE_CHARSET = "0x86"
BASE_MARKER = "ysbin\\ysc.ybn"
OUT_NAME = "update1.ypf"
INSTALL_TARGETS = ["update1.ypf", "pac/update1.ypf"]

#: hashes of the pristine build this patch was made against (see docs/PACKAGING.md)
PRISTINE_EXE_SHA256 = "99804566ff0966a3bce0206abb550d7060aa208350d3beeeca17f6898038284c"
PATCHED_EXE_SHA256 = "260137a1c25e93ff7cda8529aa3506fb1c35cfc9b2349601cc2586955f4822ad"
PRISTINE_BN_SHA256 = "41dd4d0f57adf88aa95ba8fe374e46e82e7bed686bdb236df055894b603fafa2"

#: copied into payload/tools (everything else in the kit is dev-only)
TOOL_SKIP = {"make_patcher.py", "install_cn_patch.py", "test_control_check.py",
             "test_ruby_check.py", "preview_glow_weights.py", "preview_text_spacing.py"}

HIDDEN_IMPORTS = ["ypf_tool", "build_cn_pack", "patch_yuris_charset",
                  "install_glow_sans", "verify_cn_pack"]
PYINSTALLER_EXCLUDES = ["tkinter", "unittest", "pydoc", "pdb", "doctest", "test",
                        "lib2to3", "setuptools", "pip", "wheel"]

#: wrappers in packaging/ -> names inside the release
WRAPPERS = {
    "install.bat": "安装汉化.bat",
    "install-source.bat": "安装汉化-源码版.bat",
    "uninstall.bat": "卸载汉化.bat",
    "readme-zh.txt": "说明.txt",
}


def say(text: str = "") -> None:
    print(text, flush=True)


def force_utf8_console() -> None:
    """Keep the Chinese lines from crashing a CP932/CP1252 console."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def die(text: str) -> None:
    raise SystemExit("make_patcher: " + text)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def human(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"


def copy_tree(src: Path, dst: Path, *, keep: str = "*", skip_dirs=("__pycache__",)) -> int:
    """Copy *src* (files matching *keep*) into *dst*; returns the file count."""
    count = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        here = Path(root)
        for name in sorted(files):
            if keep != "*" and not here.joinpath(name).match(keep):
                continue
            target = dst / here.relative_to(src) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(here / name, target)
            count += 1
    return count


# ------------------------------------------------------------------ input paths

def find_font(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            die(f"字体文件不存在: {path}")
        return path
    roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
             Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
             Path.cwd()]
    for root in roots:
        candidate = root / FONT_NAME
        if candidate.is_file():
            return candidate.resolve()
    die(f"找不到 {FONT_NAME}；用 --font 指定（上游: https://github.com/welai/glow-sans）")
    raise AssertionError


def find_pristine_exe(explicit: str | None, game: Path | None) -> Path:
    """The unpatched oujunoshima.exe, to derive the exe patch hashes from."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            die(f"原版 exe 不存在: {path}")
        return path
    candidates = []
    if game is not None:
        candidates += [game / (GAME_EXE + ".orig"), game / GAME_EXE]
    candidates += [KIT / "_tmp" / "pristine" / GAME_EXE,
                   KIT.parent / "_tmp" / "pristine" / GAME_EXE,
                   KIT.parent / "build" / "pristine" / GAME_EXE]
    for candidate in candidates:
        if candidate.is_file() and sha256_file(candidate) == PRISTINE_EXE_SHA256:
            return candidate.resolve()
    for candidate in candidates:
        if candidate.is_file():
            say(f"注意: {candidate} 的哈希不是已知原版，仍按它推导（--pristine-exe 可指定）")
            return candidate.resolve()
    die("找不到原版 exe；用 --pristine-exe 指定（或 --game 指向有 .orig 备份的目录）")
    raise AssertionError


def find_ysbin(explicit: str | None, game: Path | None) -> Path | None:
    """A folder of original *.ybn, used to reproduce the released pack."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not (path.is_dir() and next(path.glob("*.ybn"), None)):
            die(f"--indir {path} 里没有 *.ybn")
        return path
    for candidate in (Path(r"D:\ysbin"), KIT / "_tmp" / "ysbin",
                      KIT.parent / "yuris_text_out" / "ysbin"):
        if candidate.is_dir() and next(candidate.glob("*.ybn"), None):
            return candidate.resolve()
    return None


# ------------------------------------------------------------------- assembling

def assemble_payload(payload: Path, args: argparse.Namespace, game: Path | None) -> Path:
    """Build payload/ (nothing of the game, nothing of the user's own text)."""
    if payload.exists():
        shutil.rmtree(payload)

    tools_src = Path(args.tools).expanduser().resolve()
    count = 0
    for name in sorted(os.listdir(tools_src)):
        path = tools_src / name
        if not path.is_file():
            continue
        if name.endswith(".py") and name not in TOOL_SKIP:
            count += 1
        elif name in ("requirements.txt", "LICENSE", "NOTICE.md"):
            pass
        else:
            continue
        target = payload / "tools" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    say(f"  tools       {count} 个模块 + requirements.txt/LICENSE/NOTICE.md")

    workpack = Path(args.workpack).expanduser().resolve()
    wanted = ("lines.tsv", "usages.tsv", "scripts.tsv")
    have = [name for name in wanted if (workpack / name).is_file()]
    if "lines.tsv" not in have or "usages.tsv" not in have:
        die(f"{workpack} 里缺 lines.tsv/usages.tsv（build_cn_pack 需要这两个）")
    for name in have:
        (payload / "workpack").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workpack / name, payload / "workpack" / name)
    say(f"  workpack    {', '.join(have)}")

    font = find_font(args.font)
    (payload / "fonts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(font, payload / "fonts" / FONT_NAME)
    ofl = Path(args.ofl).expanduser().resolve() if args.ofl else KIT / "licenses" / "GlowSans-OFL.txt"
    if not ofl.is_file():
        die(f"缺字体许可证全文: {ofl}（OFL 要求随字体分发）")
    shutil.copyfile(ofl, payload / "fonts" / "OFL.txt")
    say(f"  fonts       {FONT_NAME} ({human(font.stat().st_size)}) + OFL.txt")

    yuris = Path(args.yurislib).expanduser().resolve() if args.yurislib else \
        KIT.parent / "yuris_decompiler"
    if not (yuris / "yurislib" / "fileformat.py").is_file():
        die(f"{yuris} 里没有 yurislib（clone "
            f"https://github.com/shimamura-sakura/yuris_decompiler 或 --yurislib 指定）")
    dst = payload / "yuris_decompiler"
    n = copy_tree(yuris / "yurislib", dst / "yurislib", keep="*.py")
    shutil.copyfile(KIT / "licenses" / "yurislib-MIT.txt", dst / "LICENSE")
    say(f"  yurislib    {n} 个模块 + LICENSE (MIT)")

    readme = KIT / "packaging" / "payload-readme.md"
    if readme.is_file():
        shutil.copyfile(readme, payload / "README.md")
    return payload


def prune_payload(payload: Path) -> None:
    """Drop what the tools themselves created while reproducing the pack."""
    for cache in payload.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def payload_files(payload: Path) -> dict[str, Path]:
    return {str(path.relative_to(payload)).replace(os.sep, "/"): path
            for path in sorted(payload.rglob("*")) if path.is_file()}


def reference_build(args: argparse.Namespace, payload: Path, game: Path | None,
                    scratch: Path) -> dict:
    """Reproduce the released update1.ypf from the pristine scripts."""
    sys.path.insert(0, str(KIT))
    import build_cn_pack  # noqa: E402  (kit module, needs murmurhash2)

    with tempfile.TemporaryDirectory(prefix="make-patcher-") as temp:
        indir = find_ysbin(args.indir, game)
        if indir is None:
            if game is None:
                die("无法重建参考包：请给 --indir（原版 *.ybn 目录）或 --game")
            package = game / "pac" / "bn.ypf"
            if not package.is_file():
                die(f"既没有 --indir，{package} 也不存在")
            _unpack(package, Path(temp) / "unpacked")
            indir = Path(temp) / "unpacked" / "ysbin"
        scripts = sorted(indir.glob("*.ybn"))
        say(f"  原始脚本 {len(scripts)} 个  <- {indir}")

        out = Path(temp) / "out"
        argv = ["--workpack", str(payload / "workpack"), "--indir", str(indir),
                "--out", str(out), "--td-size", args.td_size,
                "--level", str(args.level)]
        repo = payload / "yuris_decompiler"
        if (repo / "yurislib" / "__init__.py").is_file():
            argv += ["--repo", str(repo)]
        rc = build_cn_pack.main(argv)
        pack = out / OUT_NAME
        if rc not in (0, None) or not pack.is_file():
            die(f"参考重建失败（build_cn_pack -> {rc}）")
        digest, size = sha256_file(pack), pack.stat().st_size
        _, entries = _read_ypf(pack)
        say(f"  参考 {OUT_NAME}  {size} 字节  {digest[:16]}…  {len(entries)} 条目")

        published = game / OUT_NAME if game else None
        if published and published.is_file():
            have = sha256_file(published)
            say(f"  与 {published} 对比: {'一致' if have == digest else '不一致！'}")
            if have != digest:
                say(f"    游戏目录里那个是 {have[:16]}…（可能是另一版译文表，确认后再发布）")
        return {"size": size, "sha256": digest, "entries": len(entries)}


def _unpack(package: Path, out: Path) -> None:
    sys.path.insert(0, str(KIT))
    import ypf_tool  # noqa: E402
    if ypf_tool.main(["extract", str(package), str(out)]) != 0:
        die(f"解包 {package} 失败")


def _read_ypf(package: Path):
    sys.path.insert(0, str(KIT))
    import ypf_tool  # noqa: E402
    return ypf_tool.read_ypf(package)


def exe_hashes(pristine: Path, scratch: Path) -> dict:
    """Apply the exe patch to a throwaway copy to learn both hashes."""
    sys.path.insert(0, str(KIT))
    import patch_yuris_charset  # noqa: E402

    before = sha256_file(pristine)
    work = scratch / GAME_EXE
    shutil.copyfile(pristine, work)
    rc = patch_yuris_charset.main(["--exe", str(work), "--apply",
                                   "--charset", EXE_CHARSET, "--fonts", EXE_FONTS])
    if rc not in (0, None):
        die(f"patch_yuris_charset 返回 {rc}")
    after = sha256_file(work)
    for label, digest, known in (("原版", before, PRISTINE_EXE_SHA256),
                                 ("汉化后", after, PATCHED_EXE_SHA256)):
        flag = "一致" if digest == known else f"与已知值不同（{known[:16]}…）"
        say(f"  exe {label}: {digest[:16]}…  {flag}")
    return {"pristine_sha256": before, "patched_sha256": after}


def compose_manifest(args: argparse.Namespace, payload: Path, files: dict[str, Path],
                     build: dict, exe: dict, game: Path | None) -> dict:
    base = {"sha256": PRISTINE_BN_SHA256, "entry": BASE_MARKER}
    if game and (game / "pac" / "bn.ypf").is_file():
        got = sha256_file(game / "pac" / "bn.ypf")
        if got != PRISTINE_BN_SHA256:
            say(f"  注意: 游戏目录的 bn.ypf 哈希 {got[:16]}… 与已知原版不同")
    return {
        "format": 1,
        "patch_version": args.version,
        "release_name": args.name,
        "game": {"exe": GAME_EXE,
                 "folder_hint": "鏖呪ノ嶼"},
        "base_package": base,
        "install_targets": list(INSTALL_TARGETS),
        "build": {
            "workpack": "workpack",
            "repo": "yuris_decompiler",
            "td_size": args.td_size,
            "level": args.level,
            "out_name": OUT_NAME,
            "expected_size": build["size"],
            "expected_sha256": build["sha256"],
            "expected_entries": build["entries"],
        },
        "exe_patch": {
            "charset": EXE_CHARSET,
            "fonts": EXE_FONTS,
            "pristine_sha256": exe["pristine_sha256"],
            "patched_sha256": exe["patched_sha256"],
        },
        "font": {
            "family": FONT_FAMILY,
            "weight": FONT_WEIGHT,
            "bold_weight": FONT_WEIGHT,
            "line_metrics": LINE_METRICS,
            "source": FONT_NAME,
            "corpus": "workpack/lines.tsv",
        },
        "files": {rel: {"size": path.stat().st_size, "sha256": sha256_file(path)}
                  for rel, path in sorted(files.items())},
    }


# ------------------------------------------------------------------- wrappers

def write_wrappers(release: Path) -> None:
    for src_name, dst_name in WRAPPERS.items():
        src = KIT / "packaging" / src_name
        if not src.is_file():
            die(f"缺模板 {src}")
        text = src.read_text(encoding="utf-8")
        if src.suffix == ".txt":  # Windows Notepad and legacy tools want a BOM
            (release / dst_name).write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
        else:
            try:
                text.encode("ascii")
            except UnicodeEncodeError as exc:
                die(f"{src} 必须是纯 ASCII（批处理会被非 UTF-8 控制台弄乱）: {exc}")
            (release / dst_name).write_text(text, encoding="ascii", newline="\r\n")
    for name in ("LICENSE", "NOTICE.md"):
        shutil.copyfile(KIT / name, release / name)
    say(f"  包装脚本 {len(WRAPPERS)} 个 + LICENSE + NOTICE.md")


def run_pyinstaller(args: argparse.Namespace, release: Path, scratch: Path) -> None:
    python = args.python
    cmd = [python, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onedir", "--noupx", "--console", "--name", "install_cn_patch",
           "--distpath", str(scratch / "dist"), "--workpath", str(scratch / "build"),
           "--specpath", str(scratch)]
    for name in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", name]
    for name in PYINSTALLER_EXCLUDES:
        cmd += ["--exclude-module", name]
    cmd.append(str(KIT / "install_cn_patch.py"))
    say("  冻结: " + " ".join(cmd[1:4]) + f" ... ({len(cmd)} 个参数)")
    if subprocess.call(cmd) != 0:
        die("PyInstaller 失败（pip install pyinstaller 后可重试；或 --skip-freeze 只做 payload）")
    out = scratch / "dist" / "install_cn_patch"
    if not (out / "install_cn_patch.exe").is_file():
        die(f"没有生成 {out / 'install_cn_patch.exe'}")
    for item in sorted(out.iterdir()):
        target = release / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copyfile(item, target)
    exe = release / "install_cn_patch.exe"
    say(f"  install_cn_patch.exe ({human(exe.stat().st_size)}) + "
        f"_internal ({human(sum(f.stat().st_size for f in (release / '_internal').rglob('*') if f.is_file()))})")


def make_zip(release: Path, args: argparse.Namespace) -> Path:
    target = release.parent / f"{args.name}.zip"
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                zf.write(path, str(Path(args.name) / path.relative_to(release)))
    say(f"  压缩包 {target.name}  {human(target.stat().st_size)}")
    return target


# ----------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__.split("Examples::")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples::" + __doc__.split("Examples::")[-1])
    ap.add_argument("--version", default=DEFAULT_VERSION, help="patch version")
    ap.add_argument("--name", help="folder name (default: yuris-cn-patch-<version>-win64)")
    ap.add_argument("--release-dir", default=str(KIT / "release"),
                    help="where the release folder goes")
    ap.add_argument("--workpack", default=str(KIT.parent / "workpack"))
    ap.add_argument("--tools", default=str(KIT), help="kit folder to copy tools from")
    ap.add_argument("--font", help=f"upstream {FONT_NAME} (default: the Windows font folder)")
    ap.add_argument("--ofl", help="OFL full text (default: licenses/GlowSans-OFL.txt)")
    ap.add_argument("--yurislib", help="yuris_decompiler checkout (default: ../yuris_decompiler)")
    ap.add_argument("--indir", help="original *.ybn folder for the reference rebuild")
    ap.add_argument("--game", help="a game folder (base hash, exe hashes, cross-check)")
    ap.add_argument("--pristine-exe", help="unpatched oujunoshima.exe")
    ap.add_argument("--td-size", default=TD_SIZE, help=f"default: {TD_SIZE!r}")
    ap.add_argument("--level", type=int, default=9,
                    help="pack compression level (default 9, what the release was built with)")
    ap.add_argument("--python", default=sys.executable, help="interpreter used for PyInstaller")
    ap.add_argument("--manifest-only", action="store_true",
                    help="only refresh payload/ + manifest.json")
    ap.add_argument("--skip-freeze", action="store_true",
                    help="do not run PyInstaller (payload + wrappers only)")
    ap.add_argument("--zip", action="store_true", help="also write <name>.zip")
    ap.add_argument("--force", action="store_true", help="overwrite the release folder")
    return ap


def main(argv: list[str] | None = None) -> int:
    force_utf8_console()
    args = build_parser().parse_args(argv)
    if not args.name:
        args.name = f"yuris-cn-patch-{args.version}-win64"
    game = Path(args.game).expanduser().resolve() if args.game else None
    if game and not game.is_dir():
        die(f"--game {game} 不是目录")

    release = Path(args.release_dir).expanduser().resolve() / args.name
    payload = release / "payload"

    say(f"发行包 {args.name}  ({args.version})")
    if release.exists():
        if not args.force:
            die(f"{release} 已存在；确认要覆盖时加 --force")
        say(f"   --force：先删掉上一次的 {Path(args.release_dir).name}\\{args.name}\\")
        shutil.rmtree(release)
    say("1) payload ...")
    assemble_payload(payload, args, game)

    scratch = Path(tempfile.mkdtemp(prefix="make-patcher-"))
    try:
        say("2) 参考重建（得出期望的 SHA-256）...")
        build = reference_build(args, payload, game, scratch)
        say("3) exe 补丁 ...")
        pristine = find_pristine_exe(args.pristine_exe, game)
        exe = exe_hashes(pristine, scratch)

        say("4) manifest.json ...")
        prune_payload(payload)
        files = payload_files(payload)
        manifest = compose_manifest(args, payload, files, build, exe, game)
        (payload / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        say(f"  {len(manifest['files'])} 个文件入清单，"
            f"manifest.json {human((payload / 'manifest.json').stat().st_size)}")

        if args.manifest_only:
            say("--manifest-only：到此为止。")
            return 0

        say("5) 包装脚本 ...")
        write_wrappers(release)
        shutil.copyfile(KIT / "install_cn_patch.py", release / "install_cn_patch.py")
        shutil.copyfile(KIT / "requirements.txt", release / "requirements.txt")

        if not args.skip_freeze:
            say("6) 冻结补丁器 ...")
            run_pyinstaller(args, release, scratch)
        else:
            say("6) 跳过冻结（--skip-freeze）")

        total = sum(f.stat().st_size for f in release.rglob("*") if f.is_file())
        say(f"完成: {release}  {human(total)}")
        if args.zip:
            make_zip(release, args)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
