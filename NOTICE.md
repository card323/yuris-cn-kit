# NOTICE — 授权与合规说明

这份说明是给**要把这套工具或汉化补丁发出去的人**看的。四条独立的事，别混在一起：

| # | 东西 | 谁的 | 你能做什么 |
| --- | --- | --- | --- |
| 1 | 本仓库的脚本（`*.py`、文档） | 本仓库作者 | **MIT**（见 [`LICENSE`](LICENSE)）：可自由使用/修改/再分发，保留版权声明即可 |
| 2 | [yuris_decompiler](https://github.com/shimamura-sakura/yuris_decompiler)（MIT） | shimamura-sakura | 可以自由使用/再分发。**本仓库不把它拷进来**（`.gitignore` 已排除），使用者自己 `git clone`；只有**发行包**带它的一小部分（`payload/yuris_decompiler/yurislib/` + `LICENSE`，见 §2） |
| 3 | Glow Sans 字体（SIL OFL 1.1） | Celestial Phineas 等 | 可以再分发，但必须带上版权声明与 OFL 全文，且不能单独售卖（见 §3） |
| 4 | 游戏本体：`oujunoshima.exe`、`*.ypf` 里的脚本/图片 | 发行商（例：CLOCKUP） | **不要再分发**（见 §4） |

---

## §1 本仓库的脚本

工具链本身（`ypf_tool.py`、`extract_yuris_text.py`、`transcode_yuris_scripts.py`、`patch_yuris_charset.py`、`install_glow_sans.py`、`check_glossary.py` 等）是独立实现：

* `.ypf` 的解析/打包、YSTB 的读写、exe 补丁都只依据**自己对该构建的观察**（见 [docs/ENGINE_NOTES.md](docs/ENGINE_NOTES.md)）；
* 唯一带上游来源的是 `ypf_tool.py` 里的 YPF 名字混淆表（`NLTransV000/V500`、`NameXorV000/290/500`）与 `mmh2` 的调用约定——照 `yurislib/fileformat.py` 抄来，好让本工具不依赖 checkout 也能独立使用。这是 **MIT**（上游 MIT），出处已在该文件头部注明，`python ypf_tool.py selftest` 会与上游逐字节比对；
* 对 yuris_decompiler 的其余依赖是**运行时调用**（`--repo` 指向一份 checkout；发行包里这份 checkout 就放在 `payload/yuris_decompiler/`，见 §2），用于反编译 YSTB 与读取 `YSCM` 命令表。

本仓库采用 **MIT**（见根目录 [`LICENSE`](LICENSE)）：可自由使用、修改、再分发，只需保留版权声明与许可文本。提交到本仓库的贡献按同一许可接受。

## §2 yuris_decompiler（MIT）

```
git clone https://github.com/shimamura-sakura/yuris_decompiler.git
```

* 许可证：MIT，随仓库附 `LICENSE`。再分发时要保留其版权声明与许可文本。
* 本仓库**不 vendored** 它：`.gitignore` 里排除了 `yuris_decompiler/`。请在使用前自行 clone，工具默认从本目录找 `.\yuris_decompiler`（可用 `--repo` 改）。
* **例外：发行包（`docs/PACKAGING.md`）会带上它的一小部分**——`payload/yuris_decompiler/yurislib/`（3 个模块）+ `LICENSE`。原因：用户机器上没有那份 checkout，而重建脚本格式（`YSCM`/`YSTL`/XOR）必须用到它。这是 MIT 允许的再分发，随包附上 `LICENSE`（© 2025 lipsum）即满足条件；它**只在构建路径被 import**，不含任何游戏数据。

## §3 Glow Sans 字体（SIL OFL 1.1）

事实（`install_glow_sans.py` 与 `docs/ENCODING_AND_FONT.md` §4 依赖这些）：

* Glow Sans 的字体文件按 **SIL Open Font License 1.1** 发布，版权行是 `Copyright (c) 2020, Celestial Phineas`；仓库同时含一份 MIT 的 `LICENSE`（那是给**代码**的），字体本身按 OFL 走。
* 这一份 OFL **没有声明 Reserved Font Name**，所以**允许改名后再分发**——这正是 `install_glow_sans.py` 做的事（它把字体改名成 `Glow Sans SC` 之类的家族名，以便引擎的 13 字节字体名字面量放得下）。

要在你的补丁里附带字体，满足这几条即可：

1. 随字体带上 **OFL 全文** 与 **版权声明**（`install_glow_sans.py` 会生成的文件放在同一个目录，把 `OFL.txt` 一起放进去）。
2. **不能单独售卖字体**（把它捆在补丁里、免费发布，没问题）。
3. 你改过的衍生字体（改名、改 vertical metrics）**仍然是 OFL**，发布时同样带 OFL。
4. 不要暗示原作者为你的汉化项目背书。
5. 不要把字体装进 `update1.ypf`：字体由 `install_glow_sans.py` 装到系统字体目录，包里只存"字体名"（见 [docs/ENCODING_AND_FONT.md](docs/ENCODING_AND_FONT.md) §4.4）。所以**打包不影响**上面这些条件，装字体那一步才是分发点。

不附带字体也能用：字体名只要系统里存在就行，缺字由 exe 侧的回退链兜底，见 §3.4。

## §4 游戏本体

**绝对不要**发布：原版 `oujunoshima.exe`、原版 `*.ypf`、任何解包出来的 `*.ybn/*.yst`、CG/背景/菜单图片、以及**打好补丁的 exe**。

原因：这些是发行商的作品；其中 exe/脚本/图片的著作权都不在汉化者手上。打补丁后的 exe 尤其糟糕——它是"经你修改的他人程序"，既不能再分发，也没法用"用户自己打补丁"来豁免。

推荐的发布形态（按合规程度从高到低）：

| 发什么 | 说明 | 合规 |
| --- | --- | --- |
| 这套工具链 + 操作手册 | 最安全，用户自己抽自己的游戏。 | 绿 |
| **「补丁器」发行包（本仓库的 A2）** | 让用户指向自己装的游戏目录，补丁器读原版 `pac\bn.ypf`、注入译文、转码、重新打包、校验哈希后安装。包里**没有**游戏资源文件。 | 绿（唯一灰点是下面的"译文表"） |
| 你自己生成的 `update1.ypf`（形态 A1） | ⚠️ 边界模糊：它替换了原包里的引擎脚本与对白文本，属于**游戏资源的修改版衍生**。发行商通常默许（这是目前 galgame 汉化的惯例），但这是"惯例"，不是"授权"。若要发布，请附上免责声明，并说明它必须配自己合法购买的副本使用；另外 A1 少了 A2 的哈希总闸，用户版本不符时会静默出错。 | 黄 |
| 字体 | 见 §3。 | 绿 |
| 打完补丁的 exe / 原版 exe / 原版 `*.ypf` | 直接发他人作品（或者它的修改版）。 | 红 |

**A2 发行包里那个唯一的灰点**：`payload\workpack\lines.tsv`。它是"译文表"，但为了重建，
未翻译的行必须回填原文，所以这份表里**含未翻译的日文原文**（以及原文与译文的对应关系）。
它不含任何游戏**资源文件**（exe/ypf/图片都是用户本机现取的），但严格说它含游戏**文本**。
取舍：没有它就无法在用户机器上重建出逐字节一致的包（也就没有哈希总闸）。如果连这点都想避开，
只能退回到"只发工具链"那一档。`payload/README.md` 和 `docs/PACKAGING.md` §3 都写明了这一点。

> 一句话：**能发的是"怎么改"，不是"改完的游戏"**——除非你确认发行商的二次创作/补丁政策允许。

## §5 译文著作权

翻译文本的著作权属于译者。**本仓库**（版本库）不包含任何译文：`workpack/`、`translation/`、
`build/`、`yuris_text_out/`、`release/` 全在 `.gitignore` 里。把工具链发出去时，顺手检查一遍
这几个目录没有被打包进去。

**发行包**（用户下载的那个 zip，不进版本库）确实含译文表（`payload\workpack\lines.tsv`，
它是重建的输入），这是 A2 形态的必需部分。发布时请确认：译文是你自己的（或你有权分发），
并按 §4 的说明注明它含未翻译原文。若用别人的译文，先取得对方同意并按其署名要求写进 `说明.txt`。

## §6 免责与使用范围

* 这套东西**只**面向"用户对自己合法拥有的单机游戏做个人汉化"。
* 不绕过任何 DRM/授权校验：工具链里没有、也不需要完整性校验绕过（引擎侧本来就没有校验，证据见 [docs/ENGINE_NOTES.md](docs/ENGINE_NOTES.md) §6）。
* 使用本工具造成的一切后果由使用者承担。
