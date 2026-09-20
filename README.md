# YU-RIS 汉化工具链（yuris-cn-kit）

把一部**日文 YU-RIS 引擎** galgame 的脚本文本抽出来 → 翻译 → **等长**注入回编译脚本 → 打包成 `update1.ypf`，再把引擎本身从 CP932（Shift-JIS）改造成 CP936（GBK）显示。

实测对象：`鏖呪ノ嶼`（CLOCKUP，2024）——`oujunoshima.exe`，2 115 584 字节，image base `0x00400000`，`.ypf` **v500**，脚本 **YSTB V200/V300**。
本文档里的数字（16 308 行文本、227 个脚本、97 条目的包……）都来自这次实测，用来说明**规模与预期**，不是引擎常量。

> 这套工具**不能**替你把日文翻译成中文——翻译是你的工作；它负责「怎么把中文安全地塞回游戏还能跑」。

---

## 1. 它能做什么，不能做什么

**能：**

| 环节 | 做什么 |
| --- | --- |
| 解包 | 读/写/校验 `.ypf` 归档（v500，murmurhash2 校验字段会重算） |
| 抽文本 | 从 `ystNNNNN.ybn` 里把**对白文本（`WORD` 指令）**抽成「一行一句」的 TSV，并生成反编译源码便于核对 |
| 回填 | 把译文写回编译脚本的 `WORD`（对白）字符串：表达式块重建、偏移重排，**译文比原文长也行**（实测 2 字节→78 字符仍通过 8 项校验） |
| 引擎改造 | 改 exe 的 3 处硬编码（`lfCharSet`、默认字体表、DBCS 前导字节表） |
| 转码 | 把引擎脚本里的字面量从 CP932 转成 GBK，并**保留必须是 CP932 的那几类标识符** |
| 字体 | 换字体/字重/字号/字距，出离屏预览图对照（不用开游戏） |
| 守卫 | 8 项打包后校验 + 逐行 linter + 全量字符审计 + 2 个回归测试 |

**不能（或代价很大）：**

* **只能改「字符串的内容」，不能改「脚本的结构」**。注入只重写对白文本（`WORD` 命令）；引擎脚本里的字面量（字体名、资源路径、label 名）是**原位等长**改写——字体名固定 13 字节的槽位，所以改名只能 ≤12 字节。
* **对白可以比原文长**（表达式块会重建、偏移会重排，长度不限）；但长出来的部分要自己承担排版后果：一行超过约 26 个全角字符，引擎会自动分页（不截断，但会多一页），见 [docs/TRANSLATION_RULES.md](docs/TRANSLATION_RULES.md) §5。
* **不能扩长字符串后再改偏移**——整套偏移表（命令块/参数块/表达式块/行号块）都得重算，本工具链刻意不碰。
* **不能做中文名牌**（角色名想在名牌上显示中文）——那需要往编译脚本里**新增 `GOSUB` 记录**，本工具链做不到；默认方案是名牌保留日文原名（见 [docs/TRANSLATION_RULES.md](docs/TRANSLATION_RULES.md) §2）。
* **不改图片**。菜单、按钮上的文字是图片，改它们属于另一条工作线。
* **不发游戏本体**。推荐的发布形态是**只发「补丁器」**——让用户指向自己装的游戏，脚本读他本机的 `pac\bn.ypf` 现场生成包。`update1.ypf` 本身是否连带分发属于灰色地带；**绝不要**发打补丁后的 exe（见 [NOTICE.md](NOTICE.md) §4）。

---

## 2. 流水线总览

```
pac\*.ypf ──ypf_tool extract──▶ ybn 目录（ysc.ybn / yst_list.ybn / ystNNNNN.ybn）
                                  │
              ┌── extract_yuris_text ──┴─────────────┐
              ▼                                      ▼
   text\…\*.txt（纯文本，行号=脚本行号）       decompiled\…（反编译源码）
              │
   人工/AI 翻译（每行一条，UTF-8）
              │
   merge_translation ──▶ workpack\lines.tsv ──check_glossary──▶ ✔
              │
   ybn 目录 ──transcode_yuris_scripts（CP932→GBK，含 --face/--td-size）──▶ build\ysbin\
              │                                                          │
              └── inject_yuris_text（重写对白，偏移重排）──────────────────┘
                                                                         │
                              build_cn_pack（打包 + 8 项校验 + 安装）◀───┘
                                          │
                                          ▼
                              build\update1.ypf  ──▶ 游戏根目录 + pac\ 各一份

oujunoshima.exe ──patch_yuris_charset──▶ lfCharSet=0x86(936) + 默认字体表 + 前导字节表 0x81–0xFE
```

---

## 3. 前置条件

1. **Windows**。工具用到 `ctypes`/`winreg`/GDI（字体、预览、exe 补丁都是 PE32 x86）。
2. **Python 3.10+**（实测 3.14）。`pip install -r requirements.txt`（Pillow、fontTools、murmurhash2）。
3. **[yuris_decompiler](https://github.com/shimamura-sakura/yuris_decompiler)（MIT）** clone 到本目录下，得到 `.\yuris_decompiler\`（工具默认 `--repo .\yuris_decompiler`）。本仓库**不分发**它，只依赖它反编译 `YSTB`/读 `YSCM`：
   ```powershell
   git clone https://github.com/shimamura-sakura/yuris_decompiler.git
   ```
4. **你自己合法拥有的游戏本体**，以及**解包后的脚本目录**（例：`D:\ysbin`，里面是 `ysc.ybn`、`yst_list.ybn`、`yst00000.ybn…`）。抽文本、注入、打包都只需要这个目录，不需要游戏本体在跑。
5. （可选）Glow Sans 的 OTF，只在你想用那套字体时需要：见 [docs/ENCODING_AND_FONT.md](docs/ENCODING_AND_FONT.md) §4。

---

## 4. 快速开始

```powershell
# 0) 依赖
git clone https://github.com/shimamura-sakura/yuris_decompiler.git
pip install -r requirements.txt

# 1) 解包 .ypf → ybn 目录（一次）
#    输入是**原版游戏自带**的 pac\bn.ypf；update1.ypf 是本工具链的**产物**，原版游戏里没有这个文件
python ypf_tool.py list    "D:\Games\...\pac\bn.ypf"
python ypf_tool.py extract "D:\Games\...\pac\bn.ypf" D:\ysbin

# 2) 抽文本（一次；--key auto 会自动恢复 YSTB 的 4 字节异或密钥）
python extract_yuris_text.py --indir D:\ysbin --outdir yuris_text_out

# 3) 生成工作包，交给译者
python make_translation_workpack.py --indir D:\ysbin --outdir workpack

# 3b) 铺一份「逐场景」翻译骨架：translation\userscript\<场景>_中文.txt
#     （第 N 行 = 该场景第 N 行，行数必须与抽取结果一致，merge 会核对）
$dst = 'translation\userscript'; New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item 'yuris_text_out\text\data\script\userscript\*.txt' $dst
Get-ChildItem "$dst\*.txt" | Rename-Item -NewName { $_.BaseName + '_中文.txt' }

# 4) 翻译 translation\userscript\*_中文.txt（每行一句，留空=保留日文），然后合并
python merge_translation.py --apply
python check_glossary.py --lines workpack\lines.tsv          # 逐行查
python check_glossary.py --lines workpack\lines.tsv --strict # 宽度超限也当错误

# 5) 引擎改造（一次）：exe 三处补丁（默认 dry run，看清楚再 --apply）
python patch_yuris_charset.py --exe "D:\Games\...\oujunoshima.exe" --apply --fonts "Microsoft YaHei,SimHei,SimSun"

# 6) 构建：引擎脚本转码 + 注入译文 + 打包 + 8 项校验 + 安装
#    --face="" = 引擎脚本里的字体名不动（仍用原版 ＭＳ ゴシック，System32 里就有；
#                PowerShell 里空参数必须写成 --face=""，否则会被吃掉)
python build_cn_pack.py --workpack workpack --indir D:\ysbin --face="" --install --install-dir "D:\Games\..."

# 7) 可选：换 Glow Sans 并调字号/字重/字距（一条命令，自动跳过没变的步骤）
python tune_dialogue.py --size "M=30x32, NAME=30x32" --weight light --bold-weight light --game "D:\Games\..."
```

详细的每一步（参数含义、产物、耗时、失败怎么办）见 **[docs/PIPELINE.md](docs/PIPELINE.md)**。

---

## 5. 文档

| 文档 | 内容 | 谁看 |
| --- | --- | --- |
| [docs/PIPELINE.md](docs/PIPELINE.md) | **操作手册**：从解包到安装的每一步、参数、产物、校验门、工具一览 | 执行汉化的人 |
| [docs/TRANSLATION_RULES.md](docs/TRANSLATION_RULES.md) | **翻译硬约束**（模板）：前缀、ruby、禁写字符、宽度预算、自检命令 | 译者 |
| [docs/ENGINE_NOTES.md](docs/ENGINE_NOTES.md) | 引擎逆向笔记：YPF/YSTB/YSL/YSCM 格式、清单与行号、密钥恢复、exe 里 5 处 CP932 假设**以及怎么为别的构建重新定位** | 想移植/排错的人 |
| [docs/ENCODING_AND_FONT.md](docs/ENCODING_AND_FONT.md) | 编码/字符集/字体三者的关系，为什么必须是 GBK，字体许可与降级链 | 想换字体/编码的人 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 真实踩过的坑：症状 → 原因 → 处置（含两次把游戏玩崩的现场） | 出问题的人 |
| [docs/ALTERNATIVES.md](docs/ALTERNATIVES.md) | **别人怎么汉化 YU-RIS**：三条路线、可替代的现成工具（GARbro / VNTextPatch / SExtractor / YURIS_TOOLS / Translator++ / Textractor）、免封包与 JIS 替换、什么时候**不必**用本工具链、官方手册与许可要点 | 选路线的人、下一个 YU-RIS 项目 |
| [glossary/STYLE_GUIDE.md](glossary/STYLE_GUIDE.md) | 风格指南：工具报错里引用的 `section N` 章节号契约（§2.4 §3 §4.4 §8.x 等） | 被工具报错点到的人 |
| [NOTICE.md](NOTICE.md) | 第三方许可（yuris_decompiler MIT、Glow Sans OFL）与发布合规清单 | 要发布补丁的人 |

`.github/skills/yuris-cn-localization/SKILL.md` 是给 **AI 助手**用的技能包：把上面的流程、红线、校验门压缩成可执行步骤，让 agent 在仓库里直接照做（VS Code / Copilot 会自动加载 `.github/skills/*/SKILL.md`）。

---

## 6. 规模参考（一次完整汉化实测）

| 项 | 数值 |
| --- | --- |
| 抽出的可翻译行 | **16 308** 行（其中 1 592 行含 ruby 注音） |
| 涉及的编译脚本 | **227** 个 `ystNNNNN.ybn`（`yst_list.ybn` 清单共 235 条：0–181 引擎脚本 + 182–234 剧本） |
| 最终包 | `update1.ypf`，**97** 条目 / **2 111 004** 字节（只打包真正改动过的脚本） |
| 打包后校验 | 8 项，全绿才安装 |
| linter | 0 error / 690 warning（警告=宽度偏长、术语未统一之类） |
| 部署位置 | 游戏根目录 **和** `pac\` 各放一份（引擎两处都找 `update1.ypf`…`update9.ypf`） |

---

## 7. 目录

```
yuris-cn-kit\
  README.md            本文件
  LICENSE              MIT（工具代码；字体另按 OFL，见 NOTICE.md）
  NOTICE.md            第三方许可与发布合规清单
  requirements.txt     Pillow / fontTools / murmurhash2
  docs\                见上表
  .github\skills\      agent 技能
  glossary\glossary.tsv  术语表模板（自填，check_glossary.py 读它）
  glossary\STYLE_GUIDE.md 风格指南：工具报错引用的章节号契约
  *.py                 22 个命令行工具（见 docs/PIPELINE.md §8 工具一览）
  yuris_decompiler\    （自备，clone 出来，不在本仓库里）
  workpack\ build\     运行时生成的中间产物（已 .gitignore）
```

运行时的默认路径都在**当前目录**下：`--indir` 默认 `D:\ysbin`（实测用的解包目录，**换机器请显式传**），`--repo` 默认 `.\yuris_decompiler`，其它产物默认落在 `build\`。

---

## 8. 已知限制

* **对白长度不限，但排版要自己管**：译文比原文长是允许的（表达式块重建、偏移重排，实测长到 39 倍仍通过校验）；只是超过约 26 个全角字符/行就会被引擎自动分页。原文 10 195 行译文的字节长度比中位数 0.74×、p95 1.00×、最长 2.50×，实际都跑得通。
* **原位字面量必须等长**：引擎脚本里的字体名是固定 13 字节槽位（改名 ≤12 字节）、路径/label 名一个字都不能变——这些不是"替换"，是"原地改写"。
* **只有 DBCS**：GBK/CP932 这类双字节编码可用，UTF-8 不可用（偏移全按字节算）。详见 [docs/ENCODING_AND_FONT.md](docs/ENCODING_AND_FONT.md) §1。
* **4 个汉字不能用**（`镳` `锺` `矧` `矬`）：它们的 GBK 字节被引擎当控制字符，会吞字/强制翻页/停下等点击。见 §2。
* **《》《》是引擎语法**（ruby 定界符），正文里的书名要用 `〈〉`。见 §2。
* **说话人前缀照抄日文**：`名字 + 「/『/（` 必须原样保留，否则名牌空白。见 §2。
* **不能中文名牌**、**不能改图片文字**、**不能新增/删除脚本命令**。
* 引擎只在**已安装字体**里挑：写的字体名系统里没有时，`TextOutA` 会静默换字体（不崩，但观感变）。见 [docs/ENCODING_AND_FONT.md](docs/ENCODING_AND_FONT.md) §4.3。

---

## 9. 许可与合规

* **游戏本体、资源、exe、脚本文本**版权属于原厂（例：CLOCKUP）。本仓库**不含**任何游戏数据，也**不含**任何译文；发布补丁时优先只分发**补丁器**（用户拿自己那份 `pac\bn.ypf` 生成包），不要分发 exe 或原始资源。连带分发你自己生成的 `update1.ypf` 属于灰色地带，见 [NOTICE.md](NOTICE.md) §4。
* **`yuris_decompiler`** 是第三方 MIT 项目，本仓库不分发它，请自行 clone 并遵守其许可。
* **Glow Sans**：仓库代码 MIT，字体本体 SIL OFL 1.1（`Copyright (c) 2020, Celestial Phineas`，**无 Reserved Font Name 声明**）。本仓库只分发**脚本**（`install_glow_sans.py`），不带字体文件；若你要把字体打进补丁，条件见 [NOTICE.md](NOTICE.md) §3。
* 本仓库自带工具代码采用 **MIT**，见根目录 [`LICENSE`](LICENSE)（与上游 `yuris_decompiler` 同一许可）。发布时把那一个文件一起提交即可。
