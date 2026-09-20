# 打包与发布（PACKAGING）

面向**要把这套汉化做成一个"补丁包"发出去**的人。回答三个问题：发什么、怎么打、打之前怎么验。

相关：[NOTICE.md](../NOTICE.md)（谁的东西能不能发）、[PIPELINE.md](PIPELINE.md)（汉化本身怎么做）、[TROUBLESHOOTING.md](TROUBLESHOOTING.md)（用户报错怎么办）。

---

## 1. 两种发布形态

| | 形态 A1「发结果」 | 形态 A2「发现场重建」✓ |
| --- | --- | --- |
| 包里是 | 打好补丁的 `update1.ypf` + 字体 + 一个复制脚本 | **补丁器** + 译文表 + 工具链 + 字体 |
| 用户侧 | 复制文件、改 exe、装字体 | 用他自己的 `pac\bn.ypf` 重新走一遍整条链，再安装 |
| 包内含游戏数据？ | **含**（重编码后的引擎脚本与对白） | **不含**（只有译文表 + 工具；译文表见 §3 的说明） |
| 安装耗时 | 几秒 | 约 45 秒（重建 14 秒 + 字体） |
| 合法性 | 灰色（发的是"改过的游戏资源"） | 最干净：每个字节都在用户机器上生成 |
| 失败模式 | 版本不符 → 静默出问题 | 版本不符 → **哈希不符，硬失败**（见 §2） |

本仓库实现的是 **A2**：`make_patcher.py`（装配发行包）+ `install_cn_patch.py`（用户侧安装器）。
A1 想发的话从 A2 的产物里取 `update1.ypf` 就行，但§2 的那道闸就没了，见 §8。

---

## 2. A2 为什么不会把游戏改坏：结果哈希钉死

`payload/manifest.json` 里写死了「用这份译文表 + 这些工具 + 用户的 `pac\bn.ypf`，
重建出来的 `update1.ypf` 必须是这个大小、这个 SHA-256、这些条目数」。安装时：

```
[1/4] 解 pac\bn.ypf          → 临时目录\ysbin\*.ybn
[2/4] build_cn_pack          → 注入译文 → CP936 重编码 → 打包 update1.ypf
[3/4] 核 size / sha256 / 条目数   ← 不符就停，什么都不写
[4/4] 部署（两个位置）+ 改 exe + 装字体 + 改 config.sd 名
```

第 3 步是**总闸**：只要有一个字节不同，`PatchError` 直接中止，游戏目录保持原样。
所以"偷换译文表"、"工具版本不对"、"用户那份 `bn.ypf` 是别的版"都不会静默产生坏包。

第 1 步找 `bn.ypf` 的方式：扫 `pac\*.ypf` 的**目录表**（只读 32 字节头 + 表区，不读 2 GB 的 `cg.ypf`），
哪个包里有 `ysbin\ysc.ybn` 就是它，然后核 SHA-256（已知原版见 §4）。找不到就报错让用户 `--game` 指定。

---

## 3. 发行包里到底有什么

`python make_patcher.py` 产出 `release/yuris-cn-patch-<版本>-win64/`（1.0.0 实测：**50 MB**，zip 后 **26.7 MB**）：

```
install_cn_patch.exe        冻结版安装器（PyInstaller --onedir，4.2 MB）
_internal/                  它的 Python 运行时（32.0 MB；不含 tkinter/pip/setuptools 等）
install_cn_patch.py         同一个安装器的可读源码（"源码模式"用）
requirements.txt            源码模式的依赖（murmurhash2 + fontTools，Pillow 可省）
安装汉化.bat / 卸载汉化.bat   双击即用（拖游戏文件夹进去也行）
安装汉化-源码版.bat          不想跑 exe 的人用这条
说明.txt                    用户看的说明书（带 BOM，记事本友好）
NOTICE.md / LICENSE         本工具链的 MIT + 第三方许可
payload/                    安装器的全部输入（只读）
  manifest.json             清单 + 期望值（§4）
  workpack/lines.tsv        译文表（2.9 MB）
  workpack/usages.tsv       每个 id 在哪个脚本第几行（1.5 MB）
  workpack/scripts.tsv      脚本清单（4 KB）
  fonts/GlowSansSC-Normal-Light.otf + OFL.txt
  tools/*.py                工具链源码 18 个模块（源码模式与调试用）
  yuris_decompiler/yurislib/  yurislib（MIT，读写脚本格式必需）+ LICENSE
  README.md                 给"打开 payload 看的人"的解释（含下面这段）
```

上面这些数字是 `human()` 用 1 MiB = 1 MB 报出来的，和 Windows 资源管理器一致；
exe 的字节数每次 PyInstaller 都略有不同（实测 4 435 782 B），别把它当校验值——
要校验的是 §4 里那三个哈希。

**`workpack/lines.tsv` 里有未翻译的日文原文**（`orig_text` 列），这是结构决定的，不是疏忽：
重建时每个 id 都要有输出，未翻译的行必须回填原文，否则那行会变成空串。
所以发行包**不是**"零游戏文本"，只是不含任何**游戏资源文件**（exe/ypf/图片）。
这一点在 `payload/README.md` 和 [NOTICE.md](../NOTICE.md) §4 都写明了。

`.bat` 是**纯 ASCII** 的（非 UTF-8 控制台会把中文批处理弄乱），中文提示全在
`说明.txt` 和安装器输出里；`make_patcher.py` 会强制检查这一点。

---

## 4. `payload/manifest.json`

安装器的行为完全由它驱动（`install_cn_patch.py` 本身是通用的，不含本游戏的常量）。

| 字段 | 例（1.0.0） | 用途 |
| --- | --- | --- |
| `format` | `1` | schema 版本 |
| `patch_version` / `release_name` | `1.0.0` / `yuris-cn-patch-1.0.0-win64` | 显示、状态文件 |
| `game.exe` | `oujunoshima.exe` | 要在游戏目录里找的 exe 名 |
| `game.folder_hint` | `鏖呪ノ嶼` | 自动找游戏目录时的文件夹名提示 |
| `base_package.entry` | `ysbin\ysc.ybn` | 用哪个条目识别"哪个 ypf 是数据包" |
| `base_package.sha256` | `41dd4d0f…` | 已知原版 `bn.ypf`（2 705 819 B）；不符要 `--force` |
| `install_targets` | `["update1.ypf", "pac/update1.ypf"]` | 包要落到的位置（引擎两个地方都找） |
| `build.workpack` / `repo` | `workpack` / `yuris_decompiler` | 相对 payload 的路径 |
| `build.td_size` | `M=30x32, NAME=30x32` | 字号定义（要改了才改这里） |
| `build.level` | `9` | YPF 压缩级别。**必须钉死**，否则哈希对不上 |
| `build.out_name` | `update1.ypf` | 产物名 |
| `build.expected_sha256` / `expected_size` / `expected_entries` | `d5dd1425…` / `2111004` / `97` | §2 的总闸 |
| `exe_patch.charset` / `fonts` | `0x86` / `Glow Sans SC,Microsoft YaHei,SimHei` | 交给 `patch_yuris_charset.py` |
| `exe_patch.pristine_sha256` | `99804566…` | 用户那份 exe 是不是原版（不符则拒绝） |
| `exe_patch.patched_sha256` | `260137a1…` | 打完必须变成这个 |
| `font.*` | `Glow Sans SC` / `light` / `light` / `typo` / `GlowSansSC-Normal-Light.otf` / `workpack/lines.tsv` | 交给 `install_glow_sans.py` |
| `files{}` | 31 项 | payload 自身每个文件的 size + sha256，安装前先自检 |

`files` 里**不含** `manifest.json` 自己（它是在清单算完之后才写的）。

---

## 5. 用户侧发生什么（1.0.0 实测）

```
双击 安装汉化.bat（或 install_cn_patch.exe --game "D:\...\鏖呪ノ嶼"）
  ├─ 找游戏目录（自动 / 拖拽 / --game）→ 找 bn.ypf（扫目录表 + 核哈希）
  ├─ 校验 payload 31 个文件
  ├─ 解包 234 个原始脚本 → build_cn_pack 注入 16 459 条 → 打包（实测 14–25 s，看磁盘）
  ├─ 核 size/sha256/条目数 → 部署到 update1.ypf 和 pac\update1.ypf
  ├─ 改 exe 3 处 / 52 字节（备份 oujunoshima.exe.orig）→ 核 patched_sha256
  ├─ 装字体（改名 + 改 hhea 行距 → 注册两个字重槽位）
  │    最后 spawn 一个**全新的自己**（`--internal-font-verify`）确认 GDI 认这个家族名
  ├─ save\config.sd → config.sd.pre-cn-patch（--keep-config 可跳过）
  └─ 写 cn_patch_state.json（日志 cn_patch_install.log）
```

* 安装就是**默认动作**：没有 `--install` 这个开关（写了会报 `unrecognized arguments`）。
* 重跑安装不会叠加：已经装过会提示用 `--force`。
* **任何一步失败都会回滚**：日志里那批"已写入/已修改"的条目按逆序还原（`cn_patch_state.json` 是记录，回滚用内存里的 journal）。
* `--uninstall` 完全按记录还原：删掉那两个包（或还原备份）、还原 exe、注销字体、把 `config.sd` 改回来。
  实测：原版 exe、`bn.ypf`、`config.sd` **逐字节还原**，只留下 `cn_patch_install.log`（诊断用，可删）。
* `--status` 只看不写；`--dry-run` 走完整条链但一个字节都不落地（连日志都写到临时目录）。

`--internal-font-verify` 是个隐藏开关：冻结成 exe 后没法用"再启动一次 python"的方式自举，
所以安装器把自己当子进程再跑一次，只为了在**新进程**里问一次 GDI。源码模式同样走这条路。

---

## 6. 打一个发行包

```powershell
cd <工具链仓库>
python make_patcher.py --zip --force --game "D:\...\鏖呪ノ嶼"
```

六个步骤（每一步都会打印它拿到了什么）：

| 步 | 干什么 | 输入 |
| --- | --- | --- |
| 1 | 铺 `payload/`（tools / workpack / 字体 / yurislib） | `--workpack`（默认 `..\workpack`）、`--font`、`--yurislib` |
| 2 | **参考重建**：算出"本版本应该产出什么" | `--indir`（原版 `*.ybn` 目录）或 `--game`（自动解它的 `pac\bn.ypf`）；两个都不给时会去探 `D:\ysbin` 等常见位置 |
| 3 | **exe 补丁**：改一份 exe 副本，得到前后两个哈希 | `--pristine-exe` 或 `--game`（用 `*.orig`/自动找） |
| 4 | 写 `payload/manifest.json`（含 `files{}` 31 项） | 上面两步的结果 |
| 5 | 写包装脚本 + `LICENSE`/`NOTICE.md` + `install_cn_patch.py` + `requirements.txt` | `packaging/` |
| 6 | PyInstaller 冻结 `install_cn_patch.exe`（`--onedir --noupx --console`） | `--python`（默认当前解释器） |

常用开关：

* `--manifest-only`：只刷 `payload/` 和 `manifest.json`（不写包装脚本、不冻结）。
* `--skip-freeze`：铺完 payload 和包装脚本就停（没有 exe，只有源码模式）。
* `--version 1.1.0`：版本号进文件夹名、zip 名和 manifest。
* `--level N`：压缩级别，**默认 9 就是发行版用的值**；改了它 §2 的总闸就会失败（这是有意的）。
* `--force`：**先把上一次的 `release\<name>\` 整个删掉**再重铺，所以重跑永远是从零开始；
  不加它而目录已存在会直接报错退出。（早先的版本只覆盖已知文件，冻结到一半失败后
  再跑会撞上残留的 `_internal\` 而 `FileExistsError`——已修。冻结失败留下的半个目录
  不用手删，加 `--force` 重跑即可。）
* `--game` **不是**破坏性的：只读它、解到临时目录，不会写游戏目录。

依赖：`murmurhash2`、`fontTools`（打包用），`pyinstaller`（要冻结时）。字体默认从
`%LOCALAPPDATA%\Microsoft\Windows\Fonts\GlowSansSC-Normal-Light.otf` 取（上游原件，别用派生件；
派生件在 `build\glow-fonts\`）。

装配日志里这几行都是**正常**的，不是错误：

| 日志行 | 意思 |
| --- | --- |
| `16459 occurrence(s): 10314 translated, 6145 kept in Japanese, 0 left out` | 触发次数：10314 条注入了译文，6145 条没有译文（回填原文），0 条漏掉 |
| `substituted ♪ (U+266A) -> 。  x54` | `transcode_yuris_scripts.SUBSTITUTIONS` 这条固定替换表命中 54 次（括号里的 "2 from a translation" = 其中 2 次本来就写在译文里，其余是原文里的） |
| `ystNNNNN.ybn: '"･･"' - UnicodeEncodeError: … not representable` | 这个字面量在 CP936 里没有对应编码（半角片假名的浊点），于是**原样保留 CP932**；上面那句 "6 145 kept in Japanese" 就包含它，包本身没问题 |
| `Some CFF FDArray/FontDict keys were ignored upon compile` | fontTools 改名时的噪音（上游字体缺这些键） |

**改完工具链源码一定要重新跑 `make_patcher.py`**：`payload/tools/*.py` 是装配时的快照，
而安装器把 `payload/tools` 插在 `sys.path` 最前面——旧快照会**遮蔽**你刚改的代码，
报出来的错会指向旧版本的行为（踩过一次）。同理，`payload` 里每个文件的 sha256 都进了
`manifest.files{}`，**装配完就不能再动源码**（改一个字面量也要重新装配）。

---

## 7. 发布前自检（必做，10 分钟）

用**假游戏目录**测，别碰真游戏目录：

```powershell
# 0) 假游戏目录：原版 exe + pac\bn.ypf + 一个 dummy save\config.sd
$e = "$env:TEMP\patch-e2e"; $g = "$e\game"
# 1) dry run：既要看到"重建哈希 = 发布件"，也要确认游戏目录**零改动**
& "<release>\install_cn_patch.exe" --game $g --dry-run
# 2) 真装（含字体）：验证 --internal-font-verify 自举（字体校验用子进程重跑自己）
& "<release>\install_cn_patch.exe" --game $g
# 3) 装完立刻核哈希（三个产物必须等于 §4 里的值）
Get-FileHash "$g\oujunoshima.exe"        # 260137a1…（.orig 应为 99804566…）
Get-FileHash "$g\update1.ypf"            # d5dd1425…
Get-FileHash "$g\pac\update1.ypf"        # d5dd1425…
# 4) 状态与卸载
& "<release>\install_cn_patch.exe" --game $g --status
& "<release>\install_cn_patch.exe" --game $g --uninstall
# 5) 逐字节比对：exe / bn.ypf / config.sd 必须回到安装前的哈希
```

卸载会**删掉两个派生字体**（`GlowSansSC-CN-Regular/Bold.otf`）。如果你在自己机器上跑，
记得再装回去（否则改字重时"系统里没有这个家族"的警告会一直出现）：

```powershell
python install_glow_sans.py --weight light --bold-weight light --line-metrics typo `
  --family "Glow Sans SC" --font-dir <release>\payload\fonts `
  --build-dir build\glow-fonts --corpus ..\workpack\lines.tsv
```

还要跑一遍工具自己的回归：`python ypf_tool.py selftest`、`python test_ruby_check.py`、
`python test_control_check.py`，以及 `python -m py_compile <改过的脚本>`。

---

## 8. 形态 A1（想直接发 `update1.ypf`）

从 A2 的产物里取 `payload\workpack` 重建出来的那个 `update1.ypf`（或者直接从游戏目录拿），
配一个"复制到游戏目录"的批处理 + 字体 + 说明书。技术上就是 §5 的第 4 步去掉重建。

代价：**没有 §2 的那道闸**。用户装到别的版本/破解版上，会把不匹配的脚本盖进去，
症状是乱码、缺字、偶发崩溃，而且很难追。至少要在说明书里写清"只对某个版本的原版有效"，
并让用户先核 `pac\bn.ypf` 的 SHA-256。

法律上：这是"改过的游戏资源"，发行商通常默许（galgame 汉化的惯例），但**惯例不是授权**，
见 [NOTICE.md](../NOTICE.md) §4。所以本仓库默认走 A2，A1 只作为"用户坚持要单包"的备选。

---

## 9. 杀毒软件

* 冻结版是 PyInstaller `--onedir --noupx --console`：不压缩、不加壳、不做自解压，
  行为上就是"读文件、算哈希、写文件"，但启发式引擎仍然会把它标成
  `Trojan:Win32/Wacatac`、`ML.Attribute.HighConfidence` 之类。
* 缓解：① 同时发布**源码版**（`安装汉化-源码版.bat` → `pip install` → 跑 `install_cn_patch.py`），
  两条路逻辑完全一样，让用户能自己审；② zip 里附 `说明.txt` 解释误报怎么办；
  ③ 长期做法是给 exe 做代码签名（本项目没有）。
* **不要**为了"少报毒"去做 UPX 压缩或加壳，那只会更糟。
* 让用户把整个解压后的文件夹加白名单，而不是关掉杀软。

---

## 10. 发布渠道

`release/` 已 `.gitignore`：**不要把产物提交进仓库**（50 MB 二进制 + 每次重建都全变，
git 历史会迅速膨胀）。推荐：

1. 仓库里只放源码与文档（本目录的脚本 + `docs/`）。
2. `make_patcher.py --zip` 出的 `yuris-cn-patch-<版本>-win64.zip` 挂到 **GitHub Releases**（附件），
   release 说明里写：版本、支持的 `bn.ypf` SHA-256、字体与译文许可（§3、NOTICE）。
3. 逐版本留一份 `manifest.json`（或它的哈希）作为"这版发了什么"的记录。

换游戏 / 换一版译文：改 `make_patcher.py` 顶部的常量（`GAME_EXE`、`BASE_MARKER`、`EXE_FONTS`…）
或直接用 CLI 覆盖，然后重跑 §6、§7。跨游戏要重新推导的常量清单见
[PIPELINE.md](PIPELINE.md) §9。
