# 风格指南（STYLE_GUIDE）

**这份文件是「章节号契约」。** 工具在报错时给出的定位，用的就是本文件的章节号，例如：

```
[warn ] lines.tsv:12: new_text holds '锺' ... reword the line (see glossary/STYLE_GUIDE.md section 4.4)
```

所以本文件里的 **§2.4 / §3 / §4.4 / §8.x** 必须存在且对得上。**「怎么翻译」的完整说明在
[docs/TRANSLATION_RULES.md](../docs/TRANSLATION_RULES.md)**，**字体与编码的完整原理在
[docs/ENCODING_AND_FONT.md](../docs/ENCODING_AND_FONT.md)**，本文只保留「一看到就能改」的行动要点，
并顺手索引到那两份文档。

本仓库**不含任何译文的风格定稿**，也没有术语表内容——`glossary/glossary.tsv` 只是**空模板**（见 §6）。

---

## 1. 一句话总纲

译文最终会以 **GBK（代码页 936）字节**写回引擎脚本；引擎只认**成对出现的语法字符**，
不认识的字节要么画不出来，要么被当成命令。**凡是会影响解析的东西——说话人前缀、ruby 定界符、
标签名——都必须按本指南原样保留。**

---

## 2. 硬约束（违反就会崩 / 乱码 / 校验失败）

* **2.1 字符集**：最终产物是 **GBK / CP936**，不是 UTF-8。只能用 CP936 里有码位的字符；
  写不出来的字符会让构建**直接报 FATAL 拒绝整行**，不会静默丢掉。详见
  [ENCODING_AND_FONT.md](../docs/ENCODING_AND_FONT.md) §1、§3。
* **2.2 宽度**：参考作品实测**一行约 26 个全角字符、一屏 5 行**。超了不会截断，只是**自动多一页**；
  `check_glossary.py` 会把超过原文 1.25 倍的行列为警告（`--width-ratio` 可调）。
  这个数字来自字号（§8.6），换字号必须重算。
* **2.3 文件与格式**：`workpack\lines.tsv` 是 **UTF-8 BOM + CRLF + TSV**。只填 `new_text` 一列；
  **不要改 `id`、不要增删行、不要在单元格里放真实换行**。
* **2.4 校验指我们的工具，游戏自己不做完整性校验**：`ypf_tool` 只对 archive 里的
  **名称**和**数据**做 murmurhash2 存表，引擎本来就会现算这些哈希；脚本 YSTB 没有 checksum；
  exe 也没有签名自校验。所以**「文件被我改过」本身不会导致游戏报错**——
  会报错的只有**内容语义**（找不到标签、ruby 语法错、字集不对）。
  证据与实验见 [ENGINE_NOTES.md](../docs/ENGINE_NOTES.md) §8。
* **2.5 标识符类字符串必须留在 CP932**：`ysl.ybn` 里的**标签名**、脚本里作为**标识符**比较的
  字符串、OS 对话框字面量，都要保持 CP932 字节。把它们一起转码 = 游戏找不到标签，
  报 `ラベル … が見つかりませんでした`。构建时的校验 [5][6] 就是在守这一条，
  **不要用 `--no-engine-scripts` 之外的开关绕过它们**。

---

## 3. 致命规则：说话人前缀必须原样保留 ⚠️

工具报 `section 3` 时看这里（细节：[TRANSLATION_RULES.md](../docs/TRANSLATION_RULES.md) §2.1）。

* **3.1 原理**：引擎用「名字 + 开引号」的形式把说话人从正文里切出来。
  参考作品里的形式是 `名字「台词」`、`名字『台词』`、`名字（台词）`；
  切分发生在**第一个全角斜杠 `／` 或引号**处，所以前缀里的字符一旦被改动或翻译，
  名牌就会空、或者名字被当正文画进对话框。
* **3.2 因此**：前缀里的**名字照抄日文原文**（人名不译），后随的 `「` `『` `（` 原样保留；
  只翻译引号**里面**的内容。`fix_name_plates.py` 能把「前缀被译成中文」的批次批量修回，
  **默认 dry run，先看它要改什么**。
* **3.3 例外与注意**：前缀出现在**正文中间**（省略语、自言自语）时同样要保留；
  全角斜杠 `／` 若**不在** ruby 段里出现，会被当成名牌切分点 → 别在正文里用 `／`。

---

## 4. ruby（注音）处理

工具报 `section 4.4` 时看这里。ruby 语法完全由**用户脚本**定义，定界符是 `《` 和 `》`，
内部用 `／` 分隔**基字**和**读音**。参见 [ENGINE_NOTES.md](../docs/ENGINE_NOTES.md) §6.5。

* **4.1 两种 ruby**：`《字／读音》`（真注音，画在字上/后）与 `《字》`（强调，读音为空）。
* **4.2 处理规则**：段必须**成对**、不能嵌套、一个段落最多一个 `／`、强调式**只能盖一个字**。
  违反 → 校验 [7] 失败，游戏弹 `ルビ記述エラーです。` 并**结束**。
* **4.3 `《》` 是引擎语法，正文标题要用 `〈〉`**：把书名号写成 `《》` 就是开了一个 ruby 段，
  多半会被解析成「空读音」而报错。转码脚本会自动把 `≪≫` 换成 `《》`（因为它们本来就是同义符号），
  所以**你写 `≪≫` 反而会造出 ruby**——正文标题一律写 `〈〉`。
* **4.4 有些汉字会被引擎读成控制字符（`EF F0` `EF F1` `EF F2` `EF F3`）**：
  GBK 里这些字节对**确实是汉字**，但引擎在画字之前会先看字节，把它当命令：

  | 字 | 字节 | 引擎的反应 |
  | --- | --- | --- |
  | `镳` | `EF F0` | **吞掉该字**，并在行里记一条空的 "R" 记录 |
  | `锺` | `EF F1` | 画得出来（但字节对被保留作控制码） |
  | `矧` | `EF F2` | 触发**强制翻页** |
  | `矬` | `EF F3` | 插入**等待点击**，行被截断 |

  → **换词**：`分道扬镳` 这种含禁用字的词要整个换成不含这些字的近义说法（这是真实踩过的例子），不要试图逐字替代。校验 [8] 会拦，
  `test_control_check.py` 是它的自测。完整分析：[TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) §3。

---

## 5. 用词与语气

参考作品的做法：**语域固定文雅书面**，敬称按人物关系保留（`さん`→`先生/小姐` 之类要在术语表里
统一定好），口癖**保留但不加方言腔**，方言（关西腔）**不做方言对译**、改用语气词表现。
具体到作品的语气决定请写进你自己的术语表（§6）；通用写法清单见
[TRANSLATION_RULES.md](../docs/TRANSLATION_RULES.md) §4。

---

## 6. 术语（以 `glossary/glossary.tsv` 为准）

**本仓库的 `glossary/glossary.tsv` 是空模板**——术语属于译者的创作，请自己填：

```powershell
python extract_terms.py --workpack workpack --outdir glossary --min-count 2
python check_glossary.py --glossary glossary\glossary.tsv --lines workpack\lines.tsv
```

需要统一的三类：**人名/地名**（前缀里的名字**不译**，但正文里出现时要一致）、
**术法/专有名词**、**场景用词**（H 场景用词最容易前后不一）。
填完表后 `check_glossary.py` 会检查「术语表里的词在译文里是否按表写」。

---

## 7. 标点与排版细则

* 中文标点全套保留在 CP936 内，可放心用；`·`／`—`／`…` 都可用（但 `・`→`·` 会被自动替换，见下）。
* 转码脚本会自动替换四个 2 字节符号：`≪→《`、`≫→》`、`・→·`、`♪→。`
  （**注意第一个**：写 `≪≫` 会变成 ruby 定界符）。`♪` 被换掉是因为它在参考字体里无字形。
* 引号：台词内部引语用 `「」`；不要在自己的译文里补上会与引擎语法冲突的字符（`《》／`）。

---

## 8. 字体

工具报 `section 8` / `8.4` / `8.6` / `8.7` 时看这里；原理与全部坑见
[ENCODING_AND_FONT.md](../docs/ENCODING_AND_FONT.md) §4–§5，症状排查见
[TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) §4–§5。

* **8.1 为什么换字体**：引擎原本要 `ＭＳ ゴシック`，它**缺 880 个简体常用字**，缺字会画成方块；
  参考作品换成 **Glow Sans SC**（OFL 许可，可随补丁分发，见 §8.7）。
* **8.2 换字体要改三处，缺一不可**：① 安装字体并把**家族名改成脚本字面量能放下的名字**（13 字节槽位）；
  ② 脚本里的字体名字面量（`transcode_yuris_scripts.py --face`）；
  ③ exe 里**它自己硬编码的**字体名槽位与字符集（`patch_yuris_charset.py`）。只改一处 = 没反应。
* **8.3 两个坑**：字体名**按字节比较**且**第一个存在的名字生效**；名字走 `CreateFontA`（ANSI），
  所以用 ASCII 拼写（`Glow Sans SC`），不要在名字里写中文。
* **8.4 字重怎么选**：引擎只请求 **400 与 700** 两个字重，**没有抗锯齿**（1bpp 位图字体），
  所以「Regular/400」在粗体槽位里会**显得很粗**。参考作品的结论是**两个槽位都装 Light 300**
  （`install_glow_sans.py --weight light --bold-weight light`），且**必须**给 `--bold-weight`，
  否则 700 槽位仍会挑到一个粗体族 → 看起来「改细了但还是粗」。
  注意 `Book` 是 500，不是 400，容易踩。
* **8.5 删掉 `save\config.sd`**：游戏把上次的字体/字号设置存在存档目录里的这个文件，
  它会**覆盖**补丁的设置。改完字体没变化时先删/改名它再启动。
* **8.6 对白字号与字距**：参考作品 `M=30x32`、名牌 `NAME=30x32`、字距 `−2`、行距 `0`
  （`--td-size` / `--char-space` / `--line-space`，或一条命令的 `tune_dialogue.py`）。
  **字号只影响对白**——菜单是图片，改不动也不用改。字距会直接改变 §2.2 的「每行几个字」：
  前进宽度 = 字号 + 字距，30−2=28 → 750/28 ≈ 26 个全角字符/行。
* **8.7 补丁的可移植性（别人电脑上没装 Glow Sans 会怎样）**：字体名写在**包里的脚本**里，
  **字体文件不在包里**。若目标机没装该字体，GDI 会**替换成系统字体**（多半是宋体），
  排版会变但**不会崩**。所以分发时三种选择：① 要求用户自己装（最简单，零法律风险）；
  ② 把空的**家族名槽位**指向系统已有字体（`patch_yuris_charset.py --fonts "微软雅黑,黑体,宋体"`，
  第一个存在的生效）；③ 随补丁附带字体文件——**只在字体许可是 OFL 之类允许再分发时才可以**，
  并要附上字体的许可原文。

---

## 9. 工作流程

```powershell
# 0) 一次性：安装改名后的字体（换电脑才需要重跑；依赖与降级见 8.7）
python install_glow_sans.py --weight light --bold-weight light

# 1) 合并译文 → workpack\lines.tsv
python merge_translation.py --workpack workpack --translation-dir translation\userscript --apply

# 2) 逐行自查（不需要构建）
python check_glossary.py --lines workpack\lines.tsv

# 3) 严格模式：把宽度超限也当错误
python check_glossary.py --lines workpack\lines.tsv --strict

# 4) 前缀被译成中文了？机械修回（默认 dry run）
#    它读的是逐场景译文 translation\userscript\*_中文.txt，不是 lines.tsv
python fix_name_plates.py --translation-dir translation\userscript --apply

# 5) 只调字体/字号：一条命令（会重新构建并安装）
python tune_dialogue.py --size "M=30x32, NAME=30x32"

# 6) 构建（自带八项校验 → 打包 → 安装到游戏目录两处）
python build_cn_pack.py --workpack workpack --indir D:\ysbin --out build --install
```

**9.0 构建自带的八项检查**（`verify_cn_pack.py`，任何一项 FAIL 都**不要**安装）：
[1] 条目表一致、[2] 字节能用 CP936 正确解回、[3] WORD 命令集一致、[4] 布局块未被改动、
[5] OS 对话框字符串仍是 CP932、[6] 非 ASCII **标签名**仍是 CP932、[7] ruby 定界符可解析、
[8] 无引擎控制字符。逐项含义与失败后怎么办：
[TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) §7。

**9.1 只调字体/字号**：`tune_dialogue.py` 会记住上次的设置（`build\tune_state.json`），
支持 `--preview-sizes` 先出预览图，`--no-preview` 跳过预览。改**字体文件**不必重新打包，
改**字体名字面量/字号**必须重新打包（见 [ENCODING_AND_FONT.md](../docs/ENCODING_AND_FONT.md) §4.4）。
