---
name: yuris-cn-localization
description: >
  Localize a YU-RIS (E-Ris) engine visual novel into Simplified Chinese:
  unpack the .ypf archives, recover the YSTB obfuscation key, extract every
  dialogue line, inject a translation back, re-encode the engine scripts from
  CP932 to GBK, patch the executable's character set, repack update1.ypf and
  verify the result. USE FOR: extracting game text to a translator workpack;
  building or rebuilding update1.ypf; fixing YU-RIS crashes caused by
  localization (ラベル ... が見つかりませんでした, ルビ記述エラーです。,
  swallowed characters / forced page breaks); switching the dialogue font,
  weight or size; porting this toolchain to another YU-RIS title; explaining
  YPF/YSTB/YSL/YSCM formats or CP932 vs CP936 behaviour. DO NOT USE FOR:
  translating Japanese prose, editing sprites/images/CG, or writing a
  translation memory.
license: MIT
---

# YU-RIS → Simplified Chinese localization

Toolchain for repacking a YU-RIS engine game's scripts in code page 936.
Everything runs **from this kit's root**, with a Python 3.10+ interpreter and
`pip install -r requirements.txt` (Pillow, fontTools, murmurhash2).

Full detail lives in [`docs/`](../../../docs/):

| doc | read it when |
| --- | --- |
| [PIPELINE.md](../../../docs/PIPELINE.md) | executing the pipeline, looking up a tool's exact arguments |
| [TRANSLATION_RULES.md](../../../docs/TRANSLATION_RULES.md) | writing or reviewing translated text |
| [glossary/STYLE_GUIDE.md](../../../glossary/STYLE_GUIDE.md) | a tool error cites `STYLE_GUIDE.md section N` — that file owns the numbers |
| [ENGINE_NOTES.md](../../../docs/ENGINE_NOTES.md) | porting to another title, or reverse-engineering a format detail |
| [ENCODING_AND_FONT.md](../../../docs/ENCODING_AND_FONT.md) | changing font, weight, size, spacing, or encoding |
| [TROUBLESHOOTING.md](../../../docs/TROUBLESHOOTING.md) | the game crashes, looks wrong, or a check fails |
| [ALTERNATIVES.md](../../../docs/ALTERNATIVES.md) | someone asks how other groups do YU-RIS, or whether an off-the-shelf tool would be quicker |
| [AI_TRANSLATION.md](../../../docs/AI_TRANSLATION.md) | the translation is being produced by an LLM — cloud or a local Ollama model — in bulk |
| [PACKAGING.md](../../../docs/PACKAGING.md) | assembling, smoke-testing or publishing the installer release (form A2) |
| [NOTICE.md](../../../NOTICE.md) | before publishing anything |

## Invariants — never violate these

1. **Never publish the translations.** They belong to the translator. Do not
   paste more than a few sample lines into any file, PR, issue or chat. The one
   intended exception is the installer release the translator ships themselves:
   its `payload/workpack/lines.tsv` is the rebuild input (see
   [PACKAGING.md](../../../docs/PACKAGING.md) §3), and it is only distributed
   with the translator's consent.
2. **Never redistribute game assets**: no original `.ypf`, no patched `.exe`,
   no extracted scripts. A published patch is a *patcher* + the user's own
   generated `update1.ypf`. See [NOTICE.md](../../../NOTICE.md) §4.
3. **Re-derive every game-specific constant for a new title.** The key, the
   three exe patch offsets, the engine/user script index boundary, the face-name
   literal and the text-definition names are per-build. Never copy them
   blindly; [PIPELINE.md](../../../docs/PIPELINE.md) §9 lists them all.
4. **Always pass `--indir`** pointing at the *unpacked* script folder (the one
   containing `ysc.ybn`, `yst_list.ybn`, `ystNNNNN.ybn`) — the tools default to
   a path from another machine.
5. **Never edit anything in `build/` by hand**, and never hand-edit a `.ypf`.
   Rebuild from `workpack/` + `translation/`.
6. **PowerShell**: no `&&`; use `;`. Empty-string arguments are dropped, so
   write `--face=""`, not `--face ""`. Set `$env:PYTHONIOENCODING='utf-8'`
   before printing CJK, and never pipe CJK text through PowerShell stdin.
7. **A pack that changes the font name must be rebuilt**; a pack that only
   changes the font *file* must not. See [ENCODING_AND_FONT.md](../../../docs/ENCODING_AND_FONT.md) §4.4.

## Prerequisites

```powershell
$env:PYTHONIOENCODING='utf-8'
python --version                       # 3.10+
pip install -r requirements.txt
git clone https://github.com/shimamura-sakura/yuris_decompiler.git   # MIT, runtime dependency
```

`yuris_decompiler/` must sit **next to** the tools (the kit `.gitignore` keeps it
out of the published repo). Unpack the game's script archive once — the input is
the archive the **game itself ships** (the one holding `ysc.ybn`); `update1.ypf`
is *our* output, so a stock install has no such file:

```powershell
python ypf_tool.py list pac\bn.ypf                  # which archive holds ysc.ybn?
python ypf_tool.py extract pac\bn.ypf D:\ysbin      # positional outdir, not -o
```

## Ordered workflow

Run these in order. Every step prints what it did; stop at the first error.

```powershell
# 1. RECOVER THE KEY + DUMP TEXT  (proves the key by fully parsing all scripts)
python extract_yuris_text.py --indir D:\ysbin --outdir yuris_text_out -v
#    -> "key 0x801DD23F, 227 script(s)"; decompiled sources in yuris_text_out\decompiled\
#    Script line numbers here match the line numbers the game prints on a crash.

# 2. BUILD THE TRANSLATOR WORKPACK   (id / count / chars / orig_text / new_text)
python make_translation_workpack.py --indir D:\ysbin --outdir workpack
#    -> workpack\lines.tsv is the ONLY file a translator edits.
#    Per-scene scaffold (one file per scene, one line per line, same count):
$dst = 'translation\userscript'; New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item 'yuris_text_out\text\data\script\userscript\*.txt' $dst
Get-ChildItem "$dst\*.txt" | Rename-Item -NewName { $_.BaseName + '_中文.txt' }

# 3. TRANSLATE, then merge
#    Human, or an LLM: docs/AI_TRANSLATION.md covers the bulk/LLM route (prompt
#    clauses, VRAM discipline, validator + repair loop). Either way the model
#    only ever writes translation\userscript\*_中文.txt - never lines.tsv - and
#    the output must pass the same linter as human text (step 4).
python merge_translation.py --workpack workpack --translation-dir translation\userscript --apply
#    Scenes in a SUBDIRECTORY need --translation-dir <that dir>; without it merge
#    finds 0 files and still exits 0.

# 4. GATE: TEXT LEVEL  (prefixes, ruby, forbidden glyphs, width, glossary)
python check_glossary.py --lines workpack\lines.tsv
python test_ruby_check.py
python test_control_check.py

# 5. PATCH THE EXECUTABLE (dry run first; writes <exe>.orig)
python patch_yuris_charset.py --exe D:\game\game.exe                       # report
python patch_yuris_charset.py --exe D:\game\game.exe --apply --fonts "Glow Sans SC,Microsoft YaHei,SimHei"
#    Slot 0 is the dialogue face.  Use the default "Microsoft YaHei,SimHei,SimSun"
#    when you are NOT installing Glow Sans (step 6); then keep the two in sync -
#    a face name that is not installed is silently swapped for SimSun.

# 6. OPTIONAL FONT: register a face name that fits the 13-byte script literal
python install_glow_sans.py --weight light --bold-weight light
python install_glow_sans.py --verify

# 7. BUILD + VERIFY + INSTALL   (inject -> engine transcode -> pack -> 8 checks)
python build_cn_pack.py --workpack workpack --indir D:\ysbin --out build --install --install-dir D:\game
#    Installs to <game>\update1.ypf AND <game>\pac\update1.ypf.
#    A pack the game cannot read is worse than no pack: never skip --install's verify.

# 8. RE-CHECK AT ANY TIME
python verify_cn_pack.py build D:\ysbin

# 9. SHIP IT (optional): assemble the A2 installer release - the payload carries
#    the translation + tools + OFL font, NOT any game file; the installer rebuilds
#    update1.ypf from the user's own pac\bn.ypf and refuses unless the result is
#    byte-identical to what was released.
python make_patcher.py --zip --force --game D:\game
```

Then smoke-test the release in a throwaway game folder before publishing:
[PACKAGING.md](../../../docs/PACKAGING.md) §7 (`--dry-run` → install → `--status` → `--uninstall`
→ byte-compare against the snapshot).

## Gates — what must be true before shipping

| gate | command | pass looks like |
| --- | --- | --- |
| Text level | `check_glossary.py --lines workpack\lines.tsv` | `ok - 0 error(s)` |
| Ruby grammar | `test_ruby_check.py` | 18/18 |
| Control bytes | `test_control_check.py` | all pass |
| Pack level | `verify_cn_pack.py build D:\ysbin` | `PASS: … is safe to install` (8 checks) |
| Installed twice | compare SHA-256 of `build\update1.ypf` with `<game>\update1.ypf` and `<game>\pac\update1.ypf` | identical |
| Release smoke test | `install_cn_patch.exe --game <scratch> --dry-run`, then install → `--status` → `--uninstall` in a throwaway game folder | rebuild equals `manifest.build.expected_sha256`; folder byte-identical afterwards ([PACKAGING.md](../../../docs/PACKAGING.md) §7) |

The eight pack checks and what a FAIL means:
[PIPELINE.md](../../../docs/PIPELINE.md) §3, [TROUBLESHOOTING.md](../../../docs/TROUBLESHOOTING.md) §7.

## Crash playbook

The game prints `[対象ファイル] <path>` + `[場所] <line>`; map the path through
`yst_list.ybn`, then open that line in `yuris_text_out\decompiled\…`.

| symptom | cause | action |
| --- | --- | --- |
| `ラベル ｣ｴ｣ｵ…が見つかりませんでした` | a label name was transcoded; `ysl.ybn` keeps CP932 | keep label-name literals in CP932; check [6] |
| `ルビ記述エラーです。` then the game ends | `《》` in the translation — they are the ruby delimiters, not punctuation | use `〈〉` for titles; ruby must be `《base／reading》` and paired; check [7] |
| a character vanished / sudden page break / the game waits for a click | one of `镳` `锺` `矧` `矬` (`EF F0`–`EF F3` are engine control bytes) | reword; check [8] |
| font still bold, or the change had no effect | only 400/700 are requested, 1 bpp has no antialiasing, and `save\config.sd` overrides the font | go to `--weight light`; delete/rename `save\config.sd`, restart |
| still Japanese in game | wrong file name/place, or the game was not restarted | `update1.ypf` in both the root and `pac\` |

## Porting to another YU-RIS title

Do not hard-code anything. Re-derive, in this order:

1. the YSTB key — let `--key auto` recover it ([ENGINE_NOTES.md](../../../docs/ENGINE_NOTES.md) §5);
2. the engine/user script index boundary from `yst_list.ybn` (`--max-idx`);
3. the three exe patch sites by signature ([ENGINE_NOTES.md](../../../docs/ENGINE_NOTES.md) §6);
4. the face-name literal and its byte length; the text-definition names `M`/`NAME`;
5. the renderer's letter/line-spacing fields.

Then run steps 1–8 above (step 9 to package a release). If the scripts have no `YSTB` magic, the title is not
this engine generation and the kit does not apply.

Before starting, read [ALTERNATIVES.md](../../../docs/ALTERNATIVES.md): if the
target needs text only, ships loose scripts, or has no font/typography problem,
GARbro + VNTextPatch + SExtractor may cover it with far less work, and this kit's
value is the round trip, the engine-side text rules and the checks.
