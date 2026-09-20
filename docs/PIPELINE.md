# 操作手册（PIPELINE）

从「一份日文 YU-RIS 游戏」到「一个跑得起来的汉化包」的全部步骤、参数、产物与校验门。

本文里的**所有相对路径都相对本目录**（工具用 `Path(__file__).parent` 找同目录的伙伴脚本、`glossary\glossary.tsv`、`workpack\` 等），所以**请在 kit 根目录里执行命令**。

---

## 0. 约定与坑

| 约定 | 说明 |
| --- | --- |
| Shell | Windows **PowerShell**（不是 cmd）。 |
| 编码 | 先 `$env:PYTHONIOENCODING='utf-8'`，否则中文输出在某些终端里会报 `UnicodeEncodeError`。 |
| 空参数 | PowerShell 会把空字符串参数吃掉。要传空串必须写成 `--face=""`。 |
| `--indir` | **每次都要显式传**（默认写死为实测机器的 `D:\ysbin`）。 |
| 退出码 | `0` 通过 / `1` 有错（校验失败）/ `2` 输入不可读（参数错、格式错、缺文件）。 |
| CJK 不要走管道 | 用 PowerShell 管道把中文喂给 python 会乱码；要写脚本就落成 `.py` 文件再跑（文件用 UTF-8 存）。 |
| 备份 | 会改文件的工具都留 `.bak`；`patch_yuris_charset.py` 留 `<exe>.orig`。 |

---

## 1. 全流程

| 阶段 | 命令 | 跑几次 | 产物 |
| --- | --- | --- | --- |
| 0 准备 | `git clone …yuris_decompiler` / `pip install -r requirements.txt` | 一次 | `.\yuris_decompiler\` |
| 1 解包 | `ypf_tool.py extract <包> <目录>` | 一次 | `*.ybn`（例 `D:\ysbin`） |
| 2 抽文本 | `extract_yuris_text.py --indir …` | 一次 | `yuris_text_out\` |
| 3 术语表 | `extract_terms.py` | 一次 + 随译随补 | `glossary\candidates_*.tsv` → 手填 `glossary\glossary.tsv` |
| 4 工作包 | `make_translation_workpack.py` | 一次 | `workpack\{lines,usages,scripts}.tsv` |
| 5 翻译 | 人／AI 译 `translation\userscript\*_中文.txt` | 持续 | 译文 |
| 6 合并+查错 | `merge_translation.py --apply` + `check_glossary.py` | 每轮 | `workpack\lines.tsv` 的 `new_text` 列 |
| 7 exe 改造 | `patch_yuris_charset.py --apply` | 一次（每台机器） | exe 打补丁 + `.orig` 备份 |
| 8 构建 | `build_cn_pack.py --install` | 每轮 | `build\update1.ypf` + 装进游戏 |
| 9 调参/审计 | `tune_dialogue.py`／`audit_char_syntax.py`／两个 `test_*.py` | 需要时 | 预览 PNG、审计报告 |

> 3–6 是「翻译侧」循环，7–9 是「工程侧」循环。7 只需做一次；8 每改一句都要重跑（约 14–26 秒）。

---

## 2. 阶段详解

### 2.0 准备

```powershell
git clone https://github.com/shimamura-sakura/yuris_decompiler.git
pip install -r requirements.txt
```

`yuris_decompiler` 是**运行时依赖**（我们用它反编译 YSTB、读 `YSCM` 命令表），默认从本目录找 `.\yuris_decompiler`，可用 `--repo` 指到别处。**不要把它拷进你的仓库**（`.gitignore` 已排除）。

### 2.1 解包（`.ypf` → `*.ybn`）

```powershell
python ypf_tool.py list    "D:\Games\XXX\pac\bn.ypf"        # 看条目
python ypf_tool.py extract "D:\Games\XXX\pac\bn.ypf" D:\ysbin   # 解包（outdir 是位置参数，不是 -o）
python ypf_tool.py verify  "D:\Games\XXX\pac\bn.ypf" --dir D:\ysbin   # 校验每个条目的名/尺寸/哈希（--dir 必填）
```

* **输入是原版游戏自带的包**：本作是 `pac\bn.ypf`（2 705 819 字节 / 234 个条目）。`update1.ypf` 是本工具链**生成**的覆盖层，原版游戏里**没有**这个文件——不要拿它当输入。
* 游戏数据分在 11 个包里，只有 `bn.ypf` 是**剧本/引擎脚本**（`cg.ypf` 2.2 GB、`sn.ypf` 101 MB、`vo.ypf` 455 MB、`vof.ypf` 304 MB，以及 `se/op/ed1/ed2/PV/cgsys.ypf` 都是图片/语音/BGM/影片，工具链一律不碰）。**只需要脚本那个包**；别的作品里它的名字可能不同，用 `list` 找哪个包里有 `ysc.ybn`。
* 解包出来是 `ysc.ybn`（命令表）、`yst_list.ybn`（清单）、`ystNNNNN.ybn`（脚本）。把 `ysl.ybn` 也解出来如果存在（本作**没有**发它，见 [ENGINE_NOTES.md](ENGINE_NOTES.md) §4）。
* `ypf_tool.py selftest` 是自检（造包→读回→比对），改过工具后跑一下。

### 2.2 抽文本

```powershell
python extract_yuris_text.py --indir D:\ysbin --outdir yuris_text_out
```

产物：

```
yuris_text_out\decompiled\...   反编译源码（和游戏内报错的行号一一对应，查错用）
yuris_text_out\text\...         每个脚本一个 .txt，一行一句（给译者/工具用）
yuris_text_out\all_text.txt     全部文本汇总
yuris_text_out\text_index.tsv   script_idx / script_path / line_no / text
```

* **`--key auto`（默认）**：先试上游两个已知密钥，不行就统计恢复（原理见 [ENGINE_NOTES.md](ENGINE_NOTES.md) §5）。加 `-v` 可以看它打的分。
* 实测规模：227 个脚本，真正含对白（`WORD`）的有 **51 个**，共 16 459 处、**16 308 条去重行**。
* 只有 `WORD`（对白/显示字符串）会被抽出来翻译；引擎脚本里的菜单字面量不由这一步处理（由阶段 8 的转码整体处理）。

### 2.3 术语表

```powershell
python extract_terms.py                 # → glossary\candidates_*.tsv（ruby 词、说话人、片假名、汉字复合词、英文）
python extract_terms.py --workpack workpack --outdir glossary   # 或从 lines.tsv 统计
```

把定稿的译名填进 `glossary\glossary.tsv`（模板已给格式说明）。`check_glossary.py` 用它检查**拼写一致性**：同一个 `orig` 在不同行译成不同的中文就会报错。

### 2.4 工作包

```powershell
python make_translation_workpack.py --indir D:\ysbin --outdir workpack
```

```
workpack\lines.tsv    id / count / chars / orig_text / new_text  ← 只改 new_text
workpack\usages.tsv   每条 id 出现在哪个脚本、第几条命令、第几行
workpack\scripts.tsv  51 个场景脚本清单（script_idx / 文件名 / 场景名 / 行数）
workpack\README.txt   给译者的说明（工具自动生成）
```

然后在工作包里铺一份「逐场景」翻译骨架（译者按场景工作，`merge_translation.py` 依赖它）：

```powershell
$dst = 'translation\userscript'; New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item 'yuris_text_out\text\data\script\userscript\*.txt' $dst
Get-ChildItem "$dst\*.txt" | Rename-Item -NewName { $_.BaseName + '_中文.txt' }
```

* 文件名必须是 `<场景名>_中文.txt`（后缀 `_中文.txt` 是 `merge_translation.py` 的 `SUFFIX`）。
* **第 N 行对应该场景第 N 行**，行数必须和抽取结果一致——merge 会核对行数，不一致就跳过整个场景并报错。
* 行**留空 = 这一行保留日文**（构建时会把它按 GBK 重新编码，所以半成品包在游戏里依然是可读文本，不会乱码）。

### 2.5 合并与逐行检查

```powershell
python merge_translation.py --apply                 # 写回 workpack\lines.tsv（留 .bak）
python merge_translation.py --apply --only 文鳴     # 只合并场景名含该子串的
python check_glossary.py --lines workpack\lines.tsv               # 逐行检查
python check_glossary.py --lines workpack\lines.tsv --strict      # 警告也算失败
```

* merge 只会写 `new_text` 列；同一 id 被两个场景译得不一样时报错并**取 scripts.tsv 里靠前的那个**。
* `fix_name_plates.py --apply` 可以在合并前批量修「说话人前缀」问题（详见 [TRANSLATION_RULES.md](TRANSLATION_RULES.md) §3），会留 `.bak`。
* linter 检查项与消息见 §4。

### 2.6 改 exe（一次性）

```powershell
python patch_yuris_charset.py --exe "D:\Games\XXX\oujunoshima.exe"                    # dry run（默认）
python patch_yuris_charset.py --exe "D:\Games\XXX\oujunoshima.exe" --apply --fonts "Microsoft YaHei,SimHei,SimSun"
python patch_yuris_charset.py --exe "D:\Games\XXX\oujunoshima.exe" --revert           # 从 .orig 还原
```

三处改动（VA 见 [ENGINE_NOTES.md](ENGINE_NOTES.md) §6）：

| 改什么 | 作用 |
| --- | --- |
| `lfCharSet` → `0x86`（GB2312） | 让 GDI 用代码页 936 解码我们塞进去的 GBK 字节 |
| 默认字体表 3 个槽位（`Microsoft YaHei,SimHei,SimSun`） | 脚本没指定字体时的兜底链；缺字时 GDI 才不会去挑日文字体 |
| DBCS 前导字节表（0x81–0xFE） | 引擎自己算「这个字符几字节」时用的表，原版是 SJIS 的 0x81–0xFC |

* 不给 `--exe` 会自动扫本目录找 `oujunoshima.exe`；游戏 exe 叫别的名字时用 `--exe-name 别的名字.exe`。
* 打补丁前会**先备份 `<exe>.orig`**，`--revert` 用它还原，所以这一步是可逆的。
* 换游戏要重新推导这三个 VA——见 §9。

### 2.7 字体（可选）

不换字体也能汉化（引擎脚本里保留原版 `ＭＳ ゴシック`，系统自带）。要换：

```powershell
python install_glow_sans.py --weight light --bold-weight light      # 装两个字重并注册家族名
python install_glow_sans.py --verify --same-weight                  # 只验证
python install_glow_sans.py --dry-run --weight light                # 只生成改名后的文件，不安装
python install_glow_sans.py --uninstall                             # 卸载
```

* 装到用户字体目录，注册的家族名默认 `Glow Sans SC`（**必须 ≤12 字节**，因为脚本里的字体名字面量是固定 13 字节槽位）。
* **两个字重槽位都要换**：引擎的字体构造器只会请求 `lfWeight` 400 或 700，只换一个槽位另一个分支照旧。所以 `--weight light --bold-weight light` 一起给。
* ⚠️ **`save\config.sd` 会盖过字体改动**：游戏把「当前字体」持久化在这里。换字体后如果游戏里还是老样子，退出游戏、备份并删除 `save\config.sd`（副作用：音量、文字速度等设置回默认，需重设一次）。
* 字体许可与分发条件见 [NOTICE.md](../NOTICE.md) §3，降级链与字重细节见 [ENCODING_AND_FONT.md](ENCODING_AND_FONT.md) §3。

### 2.8 构建（核心一步）

```powershell
python build_cn_pack.py --workpack workpack --indir D:\ysbin --install --install-dir "D:\Games\XXX"
python build_cn_pack.py --workpack workpack --indir D:\ysbin --face "Glow Sans SC" --td-size "M=30x32, NAME=30x32" --install --install-dir "D:\Games\XXX"
```

内部四步（时间实测见 §5）：

1. **注入**（`inject_yuris_text.py`）：把 `lines.tsv` 的译文写进 51 个剧本脚本的 `WORD` 字符串。**表达式块整体重建、每条记录的偏移重排**，命令块与行号块**逐字节不变**——所以译文可以比原文长，标签、行号、控制流都不动。
2. **引擎脚本转码**（`transcode_yuris_scripts.py`，默认只处理索引 0–181）：把引擎脚本的字面量 CP932→GBK **原位等长**改写；同时改字体名（`--face`）、对白字号（`--td-size`）、字距/行距（`--char-space`/`--line-space`）。
3. **打包**（`ypf_tool.py`）：只把**改动过**的脚本打成 `build\update1.ypf`（v500，murmurhash2 字段重算）。
4. **自检**（`verify_cn_pack.py`，八项，见 §3）+ 可选安装。

常用开关：

| 开关 | 用途 |
| --- | --- |
| `--face ""` | 不改字体名（保留 `ＭＳ ゴシック`）。PowerShell 里必须写 `--face=""` |
| `--no-engine-scripts` | 不转码引擎脚本（菜单/系统文本保持日文，**调试用**） |
| `--no-fallback` | 未翻译的行不回落日文，直接不注入 |
| `--no-substitute` | 有字符无法用代码页 936 表示时报错退出（默认自动替换 4 个字符，见 §4） |
| `--no-verify` | 跳过八项校验（**别用**，除非你确切知道为什么） |
| `--level 9` | zlib 压缩级别 |
| `--out build` | 产物目录 |

**只有 `--install` 才会动游戏目录**：把 `update1.ypf` 复制到游戏根目录和 `pac\` 各一份（引擎两处都找 `update1.ypf`…`update9.ypf`，并且优先于 `bn.ypf`）。复制前请**退出游戏**（包只在启动时读一次）。

### 2.9 单独校验与回滚

```powershell
# 单独校验一份已构建的包（构建时已经自动跑过一次）
python verify_cn_pack.py build D:\ysbin
```

* 校验通过会打印 `PASS: … is safe to install`，失败会逐项列出 FAIL 并给出退出码 1。
* 安装位置：游戏根目录 `update1.ypf` **和** `pac\update1.ypf` 各一份（引擎两处都找 `update1.ypf`…`update9.ypf`）。
* **回滚**：删掉这两份 `update1.ypf` 即可（原版不带这两个文件，删了就完全回到日文）。exe 的改动用 `patch_yuris_charset.py --revert` 还原。

### 2.10 调字体/字号/字重（一条命令）

`tune_dialogue.py` 把「装字体 → 构建 → 出预览图」串成一条命令，并用 `build\tune_state.json` 记住上次的参数，**只重跑输入变了的阶段**。

```powershell
# 先只看效果，不装任何东西（出 PNG 对照图，最省事）
python tune_dialogue.py --preview-only --preview-sizes 28,30,32,34

# 改字号：约 26 秒，不动字体
python tune_dialogue.py --size "M=30x32, NAME=30x32" --game "D:\Games\XXX"

# 改字重：约 30 秒（含重装字体），两个字重一起给
python tune_dialogue.py --weight light --bold-weight light --game "D:\Games\XXX"

# 强制重做（忽略记录的状态）
python tune_dialogue.py --force --size "M=30x32" --game "D:\Games\XXX"
```

* `M` 是对白文本定义（ADV 模式），`NAME` 是名牌；`WxH` 分别是**笔进宽度**和**字形高度**，两个不是一回事（见 [ENCODING_AND_FONT.md](ENCODING_AND_FONT.md) §5）。
* 字号是全局渲染参数，**菜单用图片，不受影响**。
* 想要「只改对白、菜单不动」的效果，就只给 `M` 和 `NAME`，不要给别的定义名。
* 预览图由引擎自己的 GDI 路径渲染（`preview_yuris_font.py`），尺寸和游戏里一致，所以调参不用开游戏。

### 2.11 全量审计与回归测试

```powershell
python audit_char_syntax.py --indir D:\ysbin --overlay build\ysbin   # 逐字符审计：字符集/语法/控制字节
python audit_engine_literals.py                                       # 引擎脚本字面量审计
python test_ruby_check.py
python test_control_check.py
```

前两个把「所有会被引擎解析的字符串」再过一遍（不只看译文），用来发现**区域设置相关**的问题：汉字的字节被当成控制字符、ruby 定界符不配对、本该等长的字面量变长等。两个 `test_*.py` 是回归测试，改过 linter 后跑一下。

---

## 3. 八项校验（`verify_cn_pack.py`）

构建的最后一步自动跑；任何一项 FAIL 都会**中止并且不安装**。

| # | 检查 | 它防的是什么 |
| --- | --- | --- |
| 1 | 包与 overlay 逐字节一致 | 打包丢文件/写错条目 |
| 2 | 每条译文都能用代码页 936 解码回来 | 塞进去了引擎显示不出来的字节 |
| 3 | `WORD` 命令集合与原始脚本一致 | 注入过程增删/错位了命令 |
| 4 | 布局块（cmds/lnos/参数条数）不变 | 重排偏移时改坏了控制流/行号 |
| 5 | 系统对话框要显示的 74 条字符串仍是 CP932 | 把走 ANSI API 的字符串也改成 GBK（会变 `ｽKﾁﾋｴ_ﾕJ`） |
| 6 | 引用 `ysl.ybn` 里 58 个非 ASCII 标签名的 115 条字符串仍是 CP932 | label 名一字之差 → 游戏找不到 label 而崩溃 |
| 7 | 29 条带 ruby 定界符的行仍能解析 | `《》` 不配对 → `ルビ記述エラーです。` |
| 8 | 绘制文本里没有引擎控制字符（`EF F0–F3`） | 4 个汉字被当成控制码，吞字/翻页/停住 |

> 第 5/6/8 项的数字是本作的实测值。换游戏时数字会变，**检查本身不变**。

---

## 4. linter 消息 → 处置

`check_glossary.py --lines workpack\lines.tsv` 逐行检查，error 会让退出码变 1（`--strict` 时 warning 也算）。

| 消息 | 含义 | 处置 |
| --- | --- | --- |
| `cannot be encoded in the game's code page` | 译文里有代码页 936 表示不了的字符 | 换成等价汉字（构建时只有 4 个字符会自动替换，其它一律拒绝） |
| `holds an engine control character` | 用了 `镳`/`锺`/`矧`/`矬` | 换字。它们的 GBK 字节是 `EF F0–F3`，引擎当控制码 |
| `ruby markup does not parse` | `《》` 不配对或嵌套错 | 修 markup；正文里的书名改用 `〈〉` |
| `adds ruby markup where the original has none` | 原文没有注音，你新加了 | 删掉 |
| `more than 64 ruby spans` | 一条行里注音片段过多 | 精简（引擎有上限） |
| `speaker prefix` / 名牌相关 | 前缀不是「已注册名字 + 已注册引号」 | 见 [TRANSLATION_RULES.md](TRANSLATION_RULES.md) §3；`fix_name_plates.py --apply` 可批量修 |
| `term spelled differently from the glossary`（warning） | 同一个词译法不一致 | 统一，或补/改 `glossary\glossary.tsv` |
| `much wider than the original`（warning） | 译文比原文宽 1.25 倍以上 | 通常没事（会分页），太长就压措辞 |

构建时还会打印替换统计（`≪→《` 等 4 个字符）与「222 条字面量按设计保留 CP932」的分类摘要——**这是信息，不是错误**。

---

## 5. 耗时参考

实测机器（Windows、Python 3.14、SSD）：

| 步骤 | 时间 |
| --- | --- |
| 抽文本（227 脚本） | 约 20–40 秒 |
| 生成工作包 | 约 20 秒 |
| 完整构建（注入 3.8s + 引擎转码 3.0s + 打包 0.9s + 校验 6.2s） | **约 14 秒** |
| 只改字号重建（跳过字体） | 约 26 秒 |
| 改字重（含重装字体 + 新进程验证） | 约 50 秒 + 26 秒 |
| 预览图 | 不到 1 秒 |

`tune_dialogue.py` 的 `build\tune_state.json` 会跳过没变的阶段；`--force` 可以强制全跑。

---

## 6. 状态文件与备份

| 文件 | 谁写的 | 何时删 |
| --- | --- | --- |
| `build\tune_state.json` | `tune_dialogue.py` | 想让它忘掉上次参数时 |
| `*.bak`（`lines.tsv.bak`、场景 `.bak`） | `merge_translation.py` / `fix_name_plates.py` | 确认结果没问题后 |
| `<exe>.orig` | `patch_yuris_charset.py` | **不要删**（`--revert` 要用） |
| `save\config.sd`（游戏侧） | 游戏自己 | 换字体后没生效时备份删除 |

---

## 7. 排错速查

见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)：症状 → 原因 → 处置，包含两次真实崩游戏的现场（label 名乱码、ruby 分隔符）。

---

## 8. 工具一览

| 脚本 | 作用 | 备注 |
| --- | --- | --- |
| `ypf_tool.py` | `.ypf` 读/写/校验（v500 + murmurhash2） | `list`/`extract`/`verify`/`make`/`repack`/`selftest`，`--check` 重算哈希 |
| `extract_yuris_text.py` | 解 YSTB、抽 `WORD` 文本、调 yuris_decompiler 反编译 | `--key auto` 默认；`--no-decompile` 可跳过反编译 |
| `inject_yuris_text.py` | 把译文写回 YSTB（表达式块重建 + 偏移重排） | `--identity-check` 证明重写是字节精确的 |
| `transcode_yuris_gbk.py` | CP932↔GBK 转码、4 个字符替换、代码页 936 可用性判断 | 被其它工具 import，不单独跑 |
| `transcode_yuris_scripts.py` | 引擎脚本字面量原位转码 + 字体名/字号/字距改写 | `build_cn_pack.py` 会调它 |
| `make_translation_workpack.py` | 生成 `lines.tsv`/`usages.tsv`/`scripts.tsv`/`README.txt` | 去重，`count` 列是出现次数 |
| `merge_translation.py` | 逐场景译文合并回 `lines.tsv` | 核对行数，冲突取先出现的 |
| `fix_name_plates.py` | 批量修说话人前缀 | `--apply` 会改场景文件并留 `.bak` |
| `check_glossary.py` | 逐行 linter（字符集/术语/ruby/名牌/宽度） | `--strict`、`--width-ratio`、`--no-*` 开关 |
| `extract_terms.py` | 术语候选提取（ruby 词/说话人/片假名/汉字词） | 写给译者挑 |
| `build_cn_pack.py` | 注入 → 转码 → 打包 → 校验 →（可选）安装 | 一条命令干完，见 §2.8 |
| `verify_cn_pack.py` | 八项校验（可单独跑） | 退出码 0/1/2 |
| `audit_char_syntax.py` | 全量字符审计（原始 vs 我们的 overlay） | 发现区域设置相关隐患 |
| `audit_engine_literals.py` | 引擎脚本字面量审计 | 同上，专看引擎脚本 |
| `patch_yuris_charset.py` | exe 三处补丁（字符集/字体表/前导表） | 默认 dry run，`--revert` 可还原 |
| `install_glow_sans.py` | 改名安装 Glow Sans 两个字重并注册家族名 | OFL 条款见 NOTICE |
| `tune_dialogue.py` | 一条命令调字体/字号/字重/字距 | 状态记录 + 自动跳过 |
| `preview_yuris_font.py` | 用引擎的 GDI 路径渲染对白预览 PNG | 调参不用开游戏 |
| `preview_text_spacing.py` | 字距/行距预览 | 同上 |
| `preview_glow_weights.py` | 同一段文字的各字重对照 | 选字重用 |
| `test_ruby_check.py` | ruby linter 回归测试 | 改 linter 后跑 |
| `test_control_check.py` | 控制字符检查回归测试 | 同上 |

---

## 9. 移植到另一个 YU-RIS 游戏

工具链是通用的，但**每部游戏的常量都不一样**。下面这些都必须重新推导（方法在 [ENGINE_NOTES.md](ENGINE_NOTES.md)）：

| 常量 | 在哪 | 怎么重新得到 |
| --- | --- | --- |
| YSTB 异或密钥 | 每部游戏一个 | `--key auto` 自动恢复（统计 + 暴力验证），也可用 `extract_yuris_text.py -v` 看结果 |
| exe 里 3 个 VA | `patch_yuris_charset.py` 顶部（`VA_CHARSET`/`VA_FONT_SLOTS`/`VA_LEN_TABLE`） | 按 [ENGINE_NOTES.md](ENGINE_NOTES.md) §6 的方法找：`lfCharSet` 字节串、字体名 `_RDATA` 槽位、前导字节表 |
| exe 自动探测模式 | `AUTODETECT_PATTERNS` | 换 exe 名；`--exe-name` 可覆盖 |
| 前导字节表内容 | `patch_yuris_charset.py` 里的表 | 原版 = SJIS 的 0x81–0xFC 去掉 0xA0/0xC7/0xC8；CP936 要 0x81–0xFE |
| 要保留 CP932 的字面量家族 | `transcode_yuris_scripts.py`（`UI_CMD`/`UI_SCRIPTS`/`UI_LITERALS`/`DISPLAY_CP932`/`collect_label_names`） | 逐条核对：对话框走的 ANSI API、资源名、label 名、与剧本共享的字面量 |
| 字体名字面量 | `FACE_SOURCE`（原版名）+ `--face` | grep 引擎脚本里的 `CreateFontA` 参数字面量，长度决定新名字上限 |
| 字号定义名 | `--td-size "M=…, NAME=…"` | 看 `userdefine\文字定義.txt` 里的 `es.TDDEF.SET` 名字 |
| 字距/行距字段 | `--char-space`/`--line-space` | `userdefine\メイン定義.txt` 里两个 `gInt1144(36,19/20)` |
| 扫描/替换用的字体、宽度预算 | `docs/TRANSLATION_RULES.md` §5 | 按新字号重算 |

**发布补丁器（合规做法）**：不要分发打过补丁的 exe，也不要分发解包出来的原始资源。写一个脚本让用户指向**自己那份游戏目录**，然后依次调用：

```powershell
python patch_yuris_charset.py --exe "<用户游戏>\oujunoshima.exe" --apply --fonts "Microsoft YaHei,SimHei,SimSun"
python build_cn_pack.py --workpack workpack --indir <用户解包目录> --install --install-dir "<用户游戏>"
```

`update1.ypf` 本身是「修改过的游戏资源」，分发边界与免责声明见 [NOTICE.md](../NOTICE.md) §4。
