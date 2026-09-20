#!/usr/bin/env python3
"""Rebuild the simplified-Chinese patch from the game's own files and install it.

This is the "rebuild on the user's machine" installer (model A2 in
``docs/PACKAGING.md``): nothing derived from the game is redistributed.  Every
byte it writes is produced locally from

* the copy of the game the user already owns (``pac\\*.ypf`` and the exe),
* the translator's ``workpack/lines.tsv``,
* the SIL-OFL Glow Sans SC outline font,

by re-running the same tools the source pipeline uses::

    ypf_tool extract      the package holding ysbin\\ysc.ybn -> a scratch folder
    build_cn_pack         inject the translation, transcode to CP936, repack
    patch_yuris_charset   retarget the exe from CP932 to CP936
    install_glow_sans     put the metric-corrected face in both weight slots

Everything the run touches is journalled in ``cn_patch_state.json`` inside the
game folder, so a failure rolls back and ``--uninstall`` restores the folder.

The behaviour (which hashes are acceptable, which build options reproduce the
released pack, which fonts go where) comes from ``payload/manifest.json``: this
file is generic, the manifest is game specific.

User-facing lines are Chinese; diagnostics stay English so they can be pasted
into a bug report.  Run ``install_cn_patch.py --help`` for the options.

Examples::

    python install_cn_patch.py --dry-run         # check without touching anything
    python install_cn_patch.py                   # rebuild + install (asks nothing)
    python install_cn_patch.py --uninstall       # put the game back
    python install_cn_patch.py --status          # what is installed right now
    python install_cn_patch.py --game "D:\\games\\oujunoshima"
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

FROZEN = bool(getattr(sys, "frozen", False))
#: frozen, __file__ points inside the bundle - what we want is the release folder
HERE = Path(sys.executable if FROZEN else __file__).resolve().parent
#: how to start "this program" again - install_glow_sans respawns it to check GDI
SELF_ARGV = [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]
#: the respawn flag that tells a fresh process to just forward to install_glow_sans
FONT_VERIFY_FLAG = "--internal-font-verify"

STATE_NAME = "cn_patch_state.json"
LOG_NAME = "cn_patch_install.log"
MODULES = ("ypf_tool", "build_cn_pack", "patch_yuris_charset",
           "install_glow_sans", "verify_cn_pack")


class PatchError(Exception):
    """Something the user can act on; the message is what they get to read."""


# --------------------------------------------------------------------------- io


def say(text: str = "") -> None:
    print(text, flush=True)


def warn(text: str) -> None:
    print("  警告: " + text, flush=True)


def fail(text: str) -> None:
    raise PatchError(text)


def _force_utf8_console() -> None:
    """Make the Chinese lines survive both a 936 and a 1252 console."""
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


class _Tee:
    """Stdout plus one log file, so a failed run leaves something to send us."""

    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            try:
                stream.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def human_size(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"


def run_tool(tools: dict[str, Any], name: str, argv: list[str]) -> int:
    """Call one kit module's ``main``; several of them exit instead of returning."""
    try:
        rc = tools[name].main(argv)
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0 if rc is None else int(rc)


# ----------------------------------------------------------------------- journal


class Journal:
    """Every change the install makes, so it can be undone in reverse order."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def created(self, path: Path) -> None:
        self.entries.append({"kind": "created", "path": str(path)})

    def backed_up(self, path: Path, backup: Path) -> None:
        self.entries.append({"kind": "backed_up", "path": str(path),
                             "backup": str(backup)})

    def exe_patched(self, exe: Path, backup: Path, backup_created: bool) -> None:
        self.entries.append({"kind": "exe_patched", "path": str(exe),
                             "backup": str(backup), "backup_created": backup_created})

    def fonts_installed(self, family: str) -> None:
        self.entries.append({"kind": "fonts", "family": family})


def _rel(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return str(path.relative_to(root))
        except ValueError:
            pass
    return path.name


def undo(entries: Iterable[dict[str, Any]], tools: dict[str, Any],
         root: Path | None = None, verbose: bool = True) -> None:
    """Reverse a journal.  Never raises: uninstall has to get as far as it can."""
    for entry in reversed(list(entries)):
        kind = entry.get("kind")
        try:
            if kind == "created":
                path = Path(entry["path"])
                if path.exists():
                    path.unlink()
                    if verbose:
                        say(f"  已删除 {_rel(path, root)}")
            elif kind == "backed_up":
                path, backup = Path(entry["path"]), Path(entry["backup"])
                if not backup.exists():
                    # our file is gone or was already swapped back: leave path alone
                    if verbose:
                        say(f"  跳过 {_rel(path, root)}（找不到备份 {backup.name}）")
                    continue
                if path.exists():
                    path.unlink()
                shutil.move(str(backup), str(path))
                if verbose:
                    say(f"  已恢复 {_rel(path, root)}")
            elif kind == "exe_patched":
                exe, backup = Path(entry["path"]), Path(entry["backup"])
                if backup.exists():
                    shutil.copyfile(backup, exe)
                    if verbose:
                        say(f"  已还原 exe（来自 {backup.name}）")
                    if entry.get("backup_created"):
                        backup.unlink()
                elif verbose:
                    say(f"  提示: 没有 {backup.name}，exe 保持原样")
            elif kind == "fonts":
                if verbose:
                    say("  移除字体 ...")
                run_tool(tools, "install_glow_sans",
                         ["--uninstall", "--family", entry["family"]])
            elif verbose:
                say(f"  跳过未知记录 {kind!r}")
        except Exception as exc:  # undo must not stop at the first problem
            say(f"  撤销 {kind} 失败: {exc!r}")


# ---------------------------------------------------------------------- manifest


def load_tools(payload: Path | None = None) -> dict[str, Any]:
    """Import the kit modules, or explain what is missing."""
    candidates = [HERE, HERE / "tools", HERE.parent / "tools", HERE.parent]
    if payload is not None:
        candidates.insert(0, payload / "tools")
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    tools: dict[str, Any] = {}
    missing: list[str] = []
    for name in MODULES:
        try:
            tools[name] = importlib.import_module(name)
        except ImportError as exc:
            missing.append(f"{name}: {exc}")
        except SystemExit:
            missing.append(f"{name}: refused to load (a sibling module is missing)")
    if missing:
        fail("无法载入工具模块:\n    " + "\n    ".join(missing)
             + "\n  源码模式请先: pip install -r requirements.txt"
             + "\n  或使用发行包中的 install_cn_patch.exe")
    return tools


def find_payload(explicit: str | None, required: bool = True) -> Path | None:
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / "manifest.json").is_file():
            fail(f"{root} 下没有 manifest.json")
        return root
    candidates = [HERE.parent / "payload", HERE / "payload"]
    if HERE.name == "tools":
        candidates.insert(0, HERE.parent)
    candidates += [HERE.parent.parent / "payload"]
    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            return candidate.resolve()
    if not required:
        return None
    fail("找不到 payload\\manifest.json；请用 --payload <目录> 指定")


def load_manifest(payload: Path) -> dict[str, Any]:
    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1:
        fail(f"不认识的 manifest 版本 {manifest.get('format')!r}")
    return manifest


def verify_payload(payload: Path, manifest: dict[str, Any], tools_only: bool = False) -> None:
    """Hash every file the manifest lists, so a truncated download cannot install."""
    checked = 0
    for rel, spec in sorted(manifest.get("files", {}).items()):
        path = payload / rel
        is_tool = rel.startswith("tools/")
        if is_tool and not path.is_file():
            continue  # frozen builds carry the tools inside the exe, not on disk
        if not path.is_file():
            fail(f"payload 缺少文件 {rel}")
        want_size = spec.get("size")
        if want_size is not None and path.stat().st_size != want_size:
            fail(f"{rel} 大小不对（{path.stat().st_size} != {want_size}），下载可能不完整")
        if sha256_file(path) != spec["sha256"]:
            fail(f"{rel} 校验失败（SHA-256 不符），下载可能不完整")
        checked += 1
        if not is_tool and not tools_only:
            say(f"  {rel}  ok  ({human_size(path.stat().st_size)})")
    say(f"  payload 校验通过（{checked} 个文件）")


# -------------------------------------------------------------------- game folder


def looks_like_game(folder: Path, exe_name: str) -> bool:
    return folder.is_dir() and (folder / exe_name).is_file() and (folder / "pac").is_dir()


def find_game(explicit: str | None, manifest: dict[str, Any]) -> Path:
    exe_name = manifest["game"]["exe"]
    if explicit:
        game = Path(explicit).expanduser().resolve()
        if not game.is_dir():
            fail(f"{game} 不是文件夹")
        if not (game / exe_name).is_file():
            fail(f"{game} 里没有 {exe_name}")
        return game

    seen: list[Path] = []
    for base in (Path.cwd(), *Path.cwd().parents, HERE, HERE.parent):
        for candidate in (base, base / "game"):
            if candidate in seen:
                continue
            seen.append(candidate)
            if looks_like_game(candidate, exe_name):
                return candidate.resolve()

    if sys.stdin is not None and sys.stdin.isatty():
        say("没有自动找到游戏目录（需要同时含 " + exe_name + " 和 pac\\ 子目录）。")
        answer = input("请把补丁解压到游戏目录后回车重试，或直接输入游戏目录路径: ").strip().strip('"')
        if answer:
            return find_game(answer, manifest)

    fail("找不到游戏目录。请把补丁解压到游戏目录后运行，或用 --game \"<游戏目录>\" 指定\n"
         "  （--game 需要指向含 " + exe_name + " 和 pac\\ 子目录的那个文件夹）")


def probe_writable(game: Path) -> None:
    probe = game / (STATE_NAME + ".probe")
    try:
        probe.write_bytes(b"")
    except OSError as exc:
        fail(f"无法写入 {game}（{exc}）。若游戏装在 Program Files，请以管理员身份运行")
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()


def locate_base_package(tools: dict[str, Any], game: Path, manifest: dict[str, Any],
                        force: bool) -> tuple[Path, int, list[dict[str, Any]]]:
    """Find the package the engine scripts live in - normally ``pac\\bn.ypf``."""
    spec = manifest["base_package"]
    marker = spec["entry"]
    listed = spec["sha256"]
    accepted = {listed} if isinstance(listed, str) else set(listed)
    pac = game / "pac"
    near: list[tuple[Path, str]] = []
    for candidate in sorted(pac.glob("*.ypf")):
        try:  # names only: pac\ also holds multi-GB archives (cg.ypf is 2.2 GB here)
            version, names = tools["ypf_tool"].scan_ypf(candidate)
        except (ValueError, OSError, struct.error) as exc:
            say(f"  跳过 {candidate.name}（{exc}）")
            continue  # not a YPF archive
        if marker not in names:
            continue
        digest = sha256_file(candidate)
        if digest in accepted:
            return candidate, version, tools["ypf_tool"].read_ypf(candidate)[1]
        near.append((candidate, digest))
        if force:
            warn(f"--force: 使用未经验证的 {candidate.name} ({digest[:16]}…)；结果可能不对")
            return candidate, version, tools["ypf_tool"].read_ypf(candidate)[1]

    if near:
        listing = "\n".join(f"    {p.name}  {h}" for p, h in near)
        fail("游戏数据包不是已知的原版（SHA-256 不在清单里），为避免破坏它已停止：\n"
             + listing + "\n  已知哈希: " + ", ".join(sorted(accepted))
             + "\n  如果这是另一个版本/破解版的原版文件，可以加 --force 强行继续")
    fail(f"{pac} 里没有任何包含有 {marker}；这看起来不是本游戏的目录")


def current_state(game: Path) -> dict[str, Any] | None:
    path = game / STATE_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn(f"{STATE_NAME} 读不出来（{exc}），当作未安装")
        return None


# ------------------------------------------------------------------------- steps


def build_pack(tools: dict[str, Any], payload: Path, manifest: dict[str, Any],
               game: Path, scratch: Path, force: bool = False) -> tuple[Path, Path]:
    """Extract the game's scripts, rebuild the pack, and prove it is the release."""
    spec = manifest["build"]
    unpacked = scratch / "unpacked"
    out = scratch / "out"

    say("[1/4] 从游戏自身的数据包里解出原始引擎脚本 ...")
    package, version, entries = locate_base_package(tools, game, manifest, force=force)
    say(f"  数据包 {package.relative_to(game)}  version {version}  {len(entries)} 条目")
    if run_tool(tools, "ypf_tool", ["extract", str(package), str(unpacked)]) != 0:
        fail(f"解包失败 ({package})")
    indir = unpacked / "ysbin"
    if not indir.is_dir():
        have = sorted(p.name for p in unpacked.iterdir()) if unpacked.is_dir() else []
        fail(f"解包结果里没有 ysbin 目录：{have}")
    scripts = sorted(indir.glob("*.ybn"))
    say(f"  原始脚本 {len(scripts)} 个 -> {indir}")
    if len(scripts) != len(entries):
        warn(f"解出 {len(scripts)} 个文件，包里有 {len(entries)} 个条目")

    say("[2/4] 注入译文、转成 CP936、重新打包（这一步约十几秒）...")
    argv = ["--workpack", str(payload / spec["workpack"]),
            "--indir", str(indir),
            "--out", str(out),
            "--td-size", spec["td_size"]]
    if spec.get("level") is not None:
        argv += ["--level", str(spec["level"])]
    repo = payload / spec["repo"] if spec.get("repo") else None
    if repo is not None and (repo / "yurislib" / "__init__.py").is_file():
        argv += ["--repo", str(repo)]
    rc = run_tool(tools, "build_cn_pack", argv)
    pack = out / spec["out_name"]
    if rc != 0 or not pack.is_file():
        fail(f"重建汉化包失败（build_cn_pack 返回 {rc}）")

    say("[3/4] 校验重建结果是否与发布件一致 ...")
    size = pack.stat().st_size
    digest = sha256_file(pack)
    say(f"  {pack.name}  {size} 字节  {digest}")
    if size != spec["expected_size"] or digest != spec["expected_sha256"]:
        fail("重建结果与发布件不一致（见上面两行哈希）。\n"
             f"  期望 {spec['expected_size']} 字节 {spec['expected_sha256']}\n"
             "  这说明 payload 里的 workpack 或工具不是这一版发布用的那一套，已停止")
    if spec.get("expected_entries") is not None:
        _, back = tools["ypf_tool"].read_ypf(pack)
        if len(back) != spec["expected_entries"]:
            fail(f"重建包有 {len(back)} 个条目，期望 {spec['expected_entries']} 个")
        say(f"  条目数 {len(back)}  ok")
    return pack, indir


def deploy_pack(journal: Journal, manifest: dict[str, Any], game: Path, pack: Path,
                digest: str, dry_run: bool) -> list[str]:
    say("[4/4] 部署数据包 ...")
    installed: list[str] = []
    for rel in manifest["install_targets"]:
        target = game / rel.replace("/", os.sep)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha256_file(target) == digest:
                say(f"  {rel} 已经是汉化包，跳过备份")
                journal.created(target)
            else:
                backup = target.with_name(target.name + ".pre-cn-patch")
                index = 2
                while backup.exists():  # never clobber an older backup
                    backup = target.with_name(f"{target.name}.pre-cn-patch{index}")
                    index += 1
                if dry_run:
                    say(f"  将会备份 {rel} -> {backup.name}")
                else:
                    shutil.move(str(target), str(backup))
                    journal.backed_up(target, backup)
                    say(f"  原 {rel} 已备份为 {backup.name}")
        if dry_run:
            say(f"  将会写入 {rel}  ({human_size(pack.stat().st_size)})")
        else:
            shutil.copyfile(pack, target)
            journal.created(target)
            say(f"  已写入 {rel}  ({human_size(pack.stat().st_size)})")
        installed.append(rel)
    return installed


def patch_exe(tools: dict[str, Any], manifest: dict[str, Any], game: Path,
              journal: Journal, dry_run: bool) -> str:
    spec = manifest["exe_patch"]
    exe = game / manifest["game"]["exe"]
    say("把 exe 的文字编码从 CP932 改成 CP936 ...")
    try:  # a running game keeps its exe open, and the copy would then fail late
        with open(exe, "r+b"):
            pass
    except OSError as exc:
        fail(f"打不开 {exe.name}（{exc}）；请先关闭游戏再安装")

    before = sha256_file(exe)
    backup = Path(str(exe) + ".orig")
    backup_existed = backup.exists()
    if before == spec["patched_sha256"]:
        say("  exe 已经是汉化状态，跳过")
        journal.exe_patched(exe, backup, backup_created=False)
        return before
    if spec.get("pristine_sha256") and before != spec["pristine_sha256"]:
        warn(f"exe 与清单里的原版不同（{before[:16]}…）；如果是别的版本/破解版可能失败")

    if dry_run:
        say(f"  将会修改 3 处（字符集指令、字体名表、双字节前导字节表），"
            f"并备份为 {backup.name}")
        return before

    rc = run_tool(tools, "patch_yuris_charset",
                  ["--exe", str(exe), "--apply",
                   "--charset", spec["charset"], "--fonts", spec["fonts"]])
    if rc != 0:
        fail(f"修改 exe 失败（patch_yuris_charset 返回 {rc}）")
    journal.exe_patched(exe, backup, backup_created=not backup_existed)
    if not backup_existed:
        say(f"  原版 exe 已备份为 {backup.name}")
    after = sha256_file(exe)
    if after != spec["patched_sha256"]:
        warn(f"改完的 exe 哈希与发布件不同（{after[:16]}…）；若游戏显示异常请反馈上面两行")
    else:
        say(f"  exe 哈希 {after[:16]}… 与发布件一致")
    return after


def install_fonts(tools: dict[str, Any], manifest: dict[str, Any], payload: Path,
                  journal: Journal, scratch: Path, dry_run: bool) -> bool:
    spec = manifest["font"]
    say(f"安装字体 {spec['family']}（{spec['weight']} / {spec['bold_weight']} 两个字重槽位）...")
    if dry_run:
        say(f"  将会从 payload\\fonts\\{spec['source']} 生成并注册两个字体文件")
        return True
    argv = ["--weight", spec["weight"], "--bold-weight", spec["bold_weight"],
            "--line-metrics", spec["line_metrics"], "--family", spec["family"],
            "--font-dir", str(payload / "fonts"),
            "--build-dir", str(scratch / "glow-fonts"),
            "--corpus", str(payload / spec.get("corpus", "workpack/lines.tsv"))]
    tools["install_glow_sans"].RESPAWN_ARGV = SELF_ARGV + [FONT_VERIFY_FLAG]
    rc = run_tool(tools, "install_glow_sans", argv)
    if rc == 0:
        journal.fonts_installed(spec["family"])
        return True
    warn("字体没有装好（文字仍会显示，但字形/行距不对）；游戏照常可玩")
    return False


def handle_config_sd(journal: Journal, game: Path, dry_run: bool) -> None:
    """The game remembers a font chosen in 設定, and that overrides everything."""
    config = game / "save" / "config.sd"
    if not config.is_file():
        return
    backup = config.with_name(config.name + ".pre-cn-patch")
    if backup.exists():
        warn(f"save\\{backup.name} 已存在，保留它，本次不动 config.sd")
        return
    if dry_run:
        say(f"  将会把 save\\{config.name} 改名为 {backup.name}（旧字体选择会覆盖汉化字体）")
        return
    shutil.move(str(config), str(backup))
    journal.backed_up(config, backup)
    say(f"  save\\{config.name} 已改名为 {backup.name}（卸载时会自动恢复）")


# ------------------------------------------------------------------------- modes


def cmd_install(args: argparse.Namespace, tools: dict[str, Any], payload: Path,
                manifest: dict[str, Any]) -> int:
    game = find_game(args.game, manifest)
    say(f"游戏目录: {game}")
    existing = current_state(game)
    if existing and not args.force and not args.dry_run:
        say("检测到已经安装过（" + STATE_NAME + f"，{existing.get('installed_at', '?')}）。")
        say("  重新安装请加 --force，还原请用 --uninstall。")
        return 0

    say("校验 payload ...")
    verify_payload(payload, manifest)
    probe_writable(game)

    journal = Journal()
    scratch = Path(tempfile.mkdtemp(prefix="cn-patch-"))
    say(f"临时目录: {scratch}")
    # dry runs keep the game folder untouched, so their log goes to the scratch
    log_path = (scratch / LOG_NAME) if args.dry_run else (game / LOG_NAME)
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log, \
                contextlib.redirect_stdout(_Tee(sys.__stdout__, log)):
            say(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  "
                f"patch {manifest.get('patch_version', '?')}  game {game}")
            pack, _indir = build_pack(tools, payload, manifest, game, scratch,
                                      force=args.force)
            digest = sha256_file(pack)
            installed = deploy_pack(journal, manifest, game, pack, digest,
                                    args.dry_run)
            exe_after = patch_exe(tools, manifest, game, journal, args.dry_run)
            fonts_ok = True
            if args.skip_font:
                say("按 --skip-font 跳过字体安装")
            else:
                fonts_ok = install_fonts(tools, manifest, payload, journal, scratch,
                                         args.dry_run)
            if not args.keep_config:
                handle_config_sd(journal, game, args.dry_run)

            if args.dry_run:
                say("")
                say("--dry-run：以上都只是检查，没有改动任何文件。")
                return 0

            state = {
                "format": 1,
                "patch_version": manifest.get("patch_version"),
                "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "game": str(game),
                "pack_sha256": digest,
                "packs": installed,
                "exe_sha256": exe_after,
                "fonts_ok": fonts_ok,
                "log": LOG_NAME,
                "entries": journal.entries,
            }
            (game / STATE_NAME).write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            say("")
            say("安装完成。启动游戏即可看到简体中文。")
            say("  卸载: 运行 卸载汉化.bat（或 install_cn_patch.py --uninstall）")
            say(f"  记录: {STATE_NAME}（卸载靠它，请不要删）")
            if not fonts_ok:
                say("  注意: 字体没装好，字形可能偏小；可以重跑一次或看 " + LOG_NAME)
            if game.joinpath("save").is_dir():
                say("  提示: 若对话文字没变，见 TROUBLESHOOTING（save\\config.sd）")
            return 0
    except PatchError as exc:
        say("")
        say("错误: " + str(exc))
        if journal.entries:
            say("正在回滚这次安装已经改动的部分：")
            undo(journal.entries, tools, root=game)
        say(f"日志: {log_path}")
        return 2
    except Exception:
        say("")
        say("安装过程中出现未预期的错误，正在回滚：")
        traceback.print_exc()
        undo(journal.entries, tools, root=game)
        say(f"日志: {log_path}")
        return 1
    finally:
        if args.keep_temp:
            say(f"保留临时目录: {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)


def cmd_uninstall(args: argparse.Namespace, tools: dict[str, Any],
                  manifest: dict[str, Any]) -> int:
    game = find_game(args.game, manifest)
    state = current_state(game)
    if not state:
        say(f"{game} 里没有 {STATE_NAME}，看起来没有装过汉化补丁；没有可卸载的内容。")
        return 0
    say(f"从 {game} 卸载汉化 ...")
    entries = state.get("entries", [])
    undo(entries, tools, root=game)

    # a stale pack the state does not know about is still worth reporting
    digest = state.get("pack_sha256")
    for rel in manifest["install_targets"]:
        target = game / rel.replace("/", os.sep)
        if target.exists() and digest and sha256_file(target) == digest:
            target.unlink()
            say(f"  已删除 {rel}")
        elif target.exists():
            warn(f"{rel} 不是本补丁写的（内容已变），保留不动")

    say("")
    say("卸载完成，游戏已回到原版。")
    if (game / LOG_NAME).is_file():
        say(f"  {LOG_NAME}（安装日志）留着没删，可以自己删掉")
    if args.keep_state:
        say(f"保留 {STATE_NAME}（--keep-state）")
    else:
        with contextlib.suppress(OSError):
            (game / STATE_NAME).unlink()
            say(f"  已删除 {STATE_NAME}")
    return 0


def cmd_status(args: argparse.Namespace, tools: dict[str, Any],
               manifest: dict[str, Any]) -> int:
    game = find_game(args.game, manifest)
    state = current_state(game)
    exe = game / manifest["game"]["exe"]
    say(f"游戏目录: {game}")
    if exe.is_file():
        say(f"exe: {exe.name}  {sha256_file(exe)[:16]}…")
    else:
        say(f"exe: 找不到 {exe.name}")
        return 0
    if not state:
        say("状态: 未安装（没有 " + STATE_NAME + "）")
        return 0
    say(f"状态: 已安装 {state.get('installed_at', '?')}  patch "
        f"{state.get('patch_version', '?')}")
    for rel in state.get("packs", []):
        target = game / rel.replace("/", os.sep)
        if not target.is_file():
            say(f"  {rel}: 缺失")
            continue
        digest = sha256_file(target)
        mark = "ok" if digest == state.get("pack_sha256") else "内容已变"
        say(f"  {rel}: {mark}  {digest[:16]}…")
    fonts_ok = state.get("fonts_ok")
    say(f"  字体: {'已装' if fonts_ok else '未装好'}")
    if not exe.is_file():
        return 0
    exe_hash = sha256_file(exe)
    if state.get("exe_sha256") == exe_hash:
        say("  exe: 汉化状态")
    else:
        say(f"  exe: 与记录不同（{exe_hash[:16]}…）")
    return 0


# -------------------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Rebuild and install the simplified-Chinese patch (model A2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples::")[-1].strip())
    ap.add_argument("--game", help="game folder (default: autodetect around the "
                                   "current directory and this program)")
    ap.add_argument("--payload", help="folder holding manifest.json (default: "
                                      "<release>\\payload)")
    ap.add_argument("--uninstall", action="store_true",
                    help="undo an install using cn_patch_state.json")
    ap.add_argument("--status", action="store_true", help="show what is installed")
    ap.add_argument("--dry-run", action="store_true",
                    help="check everything, change nothing")
    ap.add_argument("--force", action="store_true",
                    help="continue although the data package or the exe is not the "
                         "known original, or although a patch is already installed")
    ap.add_argument("--skip-font", action="store_true",
                    help="do not install the bundled font")
    ap.add_argument("--keep-config", action="store_true",
                    help="leave save\\config.sd alone")
    ap.add_argument("--keep-temp", action="store_true",
                    help="keep the scratch folder (the build outputs)")
    ap.add_argument("--keep-state", action="store_true",
                    help="with --uninstall: keep cn_patch_state.json")
    ap.add_argument(FONT_VERIFY_FLAG, nargs=argparse.REMAINDER,
                    help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version",
                    version="install_cn_patch.py (part of the yuris-cn-kit)")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _force_utf8_console()

    if argv[:1] == [FONT_VERIFY_FLAG]:
        # install_glow_sans respawned us: just forward to its --verify
        tools = load_tools(HERE / "payload")
        tools["install_glow_sans"].RESPAWN_ARGV = SELF_ARGV + [FONT_VERIFY_FLAG]
        return run_tool(tools, "install_glow_sans", argv[1:])

    args = build_parser().parse_args(argv)
    tools = load_tools(find_payload(args.payload, required=False))
    try:
        if args.status or args.uninstall:
            payload = find_payload(args.payload, required=False)
            manifest = load_manifest(payload) if payload else {
                "game": {"exe": _guess_exe(args.game)}}
            if args.status:
                return cmd_status(args, tools, manifest)
            if not payload:
                fail("--uninstall 需要 --payload（或把补丁解压到游戏目录后运行）")
            return cmd_uninstall(args, tools, manifest)

        payload = find_payload(args.payload)
        manifest = load_manifest(payload)
        return cmd_install(args, tools, payload, manifest)
    except PatchError as exc:
        say("")
        say("错误: " + str(exc))
        return 2
    except KeyboardInterrupt:
        say("已取消。")
        return 130


def _guess_exe(game: str | None) -> str:
    """--status/--uninstall without a manifest still needs an exe name."""
    if game:
        found = sorted(Path(game).glob("*.exe"))
        if len(found) == 1:
            return found[0].name
    return "oujunoshima.exe"


if __name__ == "__main__":
    raise SystemExit(main())
