# 替代方案对照：业界怎么汉化 YU-RIS 游戏

本文回答三个问题：**别人用什么方法做 YU-RIS 汉化**、**有哪些现成工具能替代本工具链的某一步**、**什么时候该用哪条路**。
所有外部工具都给出来源与"支持到什么程度"的证据等级（`已核实代码` > `已核实文档` > `未核实`）。

> 本文只写引擎、格式、工具与许可事实，**不含任何游戏文本或译文**。

---

## 1. 三条技术路线

| 路线 | 做法 | 产物能分发吗 | 中文显示怎么解决 |
| --- | --- | --- | --- |
| **A. 运行时挂钩 + 机翻叠加** | 挂钩引擎文本绘制，翻译后叠在原文字上 | ✗（只有你自己看得见） | 靠叠加层自己画字，不碰引擎 |
| **B. 静态抽取 / 回填** | 拆包 → 抽文本 → 翻译 → 写回 → 重打包 | ✓ | 视工具而定，多数**不管** |
| **C. 中文社区针对 YU-RIS 的专门做法** | 在 B 的基础上补「引擎汉字化 / JIS 替换 / 免封包」 | ✓ | 改 exe 字符集，或换码位映射字体 |

**本工具链 = B + C 的交集，再加上公开工具都不覆盖的那一段**（字体/字重、控制字节、ruby 与 label 语法崩溃、8 项打包校验）。第 5 节逐项对照。

---

## 2. 工具清单

| 工具 | 对 YU-RIS 的支持 | 证据 | 能替代本工具链的哪一步 | 不能替代什么 |
| --- | --- | --- | --- | --- |
| [GARbro](https://github.com/morkt/GARbro) | `.ypf` 解包、`.ycg` 图片转换 | 已核实代码：`ArcFormats/YuRis/ArcYPF.cs`、`ImageYCG.cs` | `ypf_tool.py extract` | 回填、重打包、字体、编码 |
| [VNTranslationTools（VNTextPatch）](https://github.com/arcusmaximus/VNTranslationTools) | YU-RIS 脚本抽取 + 回填；附**完整二进制格式说明** | 已核实代码：`VNTextPatch.Shared/Scripts/Yuris/`（`YurisScenarioScript.cs`、`YurisCommandList.cs`、`YurisConfigScript.cs`、`Notes.txt`） | `extract_yuris_text.py` | 中文字形、字体、控制字节、打包校验 |
| [SExtractor](https://github.com/satan53x/SExtractor)（502★） | 引擎列表含 `Yu-ris`；BIN 模式参数 `version=0`、`decrypt=auto`（自动猜 XOR key）就是为 YU-RIS 写的；另有 `Yuris_txt (非ybn)` 预设 | 已核实文档 | 抽文本/回填 | 字体、引擎汉字化需配它生态里的 `Font`（JIS 替换字体）+ UniversalInjectorFramework |
| [YURIS_TOOLS](https://github.com/jyxjyx1234/YURIS_TOOLS)（51★，活跃） | 「新版 YU-RIS 引擎汉化工具包」，中文流程与本文档最接近（见 §3.3） | 已核实文档（README） | 抽文本/回填、人名定义、引擎汉字化 | 封包（作者明写「没有研究。祈祷游戏支持免封包吧」）、字体、控制字节 |
| [RxYuris](https://github.com/ZQF-ReVN/RxYuris)（68★，已归档） | `.ypf` / `.ybn`，C++；`YSTL_Parse.exe`（还原脚本原名）、`YSTB_GuessXorKey.exe`（猜密钥）出自这里 | 已核实文档（YURIS_TOOLS 引用其 commit） | 还原 `yst_list.ybn` 里的原始路径名、猜密钥 | 全流程 |
| [YuRISTools](https://github.com/fengberd/YuRISTools)（59★，已归档） | C# 工具集 | 已核实文档 | 同上，另一实现 | — |
| [YU-RIS-Script-Editor](https://github.com/Aionfatedio/YU-RIS-Script-Editor) | YU-RIS 脚本编辑器（Python） | 已核实仓库存在 | 人工编辑脚本 | 未核实功能深度 |
| [yuris_decompiler](https://github.com/shimamura-sakura/yuris_decompiler)（已归档） | 反编译（v0.255–v0.494）——**本工具链的依赖** | 实际操作过 | 反编译 `YSTB` / 读 `YSCM` | 编译、编码、字体、打包 |
| [yuri](https://github.com/shimamura-sakura/yuri) | 反编译**＋重新编译**（并行），附 `patch_text.py`（对白抽取/回填）、`gbk.py`（引擎汉字化） | 已核实文档 | 可望替代「反编译 + 二进制注入」两步（未实测） | 字体、控制字节、打包校验 |
| [Textractor](https://github.com/Artikash/Textractor) | 专用 YU-RIS 挂钩 | 已核实代码：`texthook/engine/engine.h:158` `bool InsertYurisHook();  // YU-RIS: *.ypf` | 路线 A：自己玩时的实时对照 | 任何可分发的补丁 |
| [Translator++](https://github.com/dreamsavior/TranslatorPlusPlus) | 引擎表里明确列有 **YU-RIS** | 已核实文档（README） | 翻译工序：表格/记忆库/机翻调度/OCR | 不解决拆包密钥（README 原文：自定义加密与封包可能需先自行解包或写 Custom Parser）、不解决中文编码与字体 |

**最值得先读的一份资料**：`VNTranslationTools/VNTextPatch.Shared/Scripts/Yuris/Notes.txt`——里面把 `YSCM / YSCF / YSER / YSLB / YSTD / YSTL / YSTB / YSVR` 的结构和那个小型表达式 VM 的 opcode 写得清清楚楚。本文档 [ENGINE_NOTES.md](ENGINE_NOTES.md) 里那些逆向结论，上游早有公开记录；**做第二个 YU-RIS 游戏时先读它，能省掉大半逆向工作量**。

---

## 3. 路线详解与代价

### 3.1 运行时挂钩（Textractor / LunaTranslator 一类）

* 适合：自己通关时看大意、做翻译前的语义参考。**不需要**改包、改 exe、动字体。
* 代价：只有本机可见，**不能做成补丁发给别人**；不解决排版、字重、字形；对"名字牌"这类由脚本控制的显示无效。
* 结论：**当辅助手段用，不当交付物**。

### 3.2 静态抽取 / 回填（VNTextPatch、SExtractor、YURIS_TOOLS 等）

* 适合：要出补丁。
* 代价：这些工具都止步于"文本内容"，**中文能不能显示出来是另一个问题**。YU-RIS 是 CP932 世界：直接把 UTF-8/GBK 中文塞回去，要么花屏、要么缺字、要么被当控制字节吞掉。
* 所以真正的分界线不是"会不会抽文本"，而是**"抽完之后怎么让中文长出来"**——这就是下面三条（3.3–3.5）的差别。

### 3.3 引擎汉字化：把 exe 的字符集改成 CP936

* 做法：patch 主 exe 的 `lfCharSet`（本工具链见 `patch_yuris_charset.py`），脚本字面量从 CP932 转成 GBK，译文用 GBK 编码写回。
* **这是中文社区的主流做法，不是本工具链的独创**：
  * `YURIS_TOOLS/GBK.py`：需要把 exe 放到脚本同目录，手动填 exe 名；报错说明该游戏不支持。
  * `yuri/gbk.py`：注明 "Modified from jyxjyx1234/YURIS_TOOLS/blob/main/GBK.py"。
* 本工具链比它们多做了两件事：**同时改写默认字体表与前导字节表**（`0x81–0xFE`），以及**把不能用的汉字挡在门外**（见 3.6）。
* 代价：改了 exe，**补丁不能分发改好的 exe**（版权），只能发「补丁器 + 你自己生成的 `.ypf`」（见 [../NOTICE.md](../NOTICE.md) §4/§6）。

### 3.4 JIS 替换 / 码位映射字体（不改脚本编码）

* 做法：脚本仍按 Shift-JIS 存，靠**自制字体把中文字形画到 SJIS 码位上**；或再用代理 DLL（UniversalInjectorFramework / VNTProxy 一类）在 API 层把文本换掉。
* 优点：不动 exe、不重打包、不转码，回滚容易。
* 代价：要造一个巨大的映射字体；**对"引擎按字节判断"的地方无效**——本作遇到的 `EF F0/F1/F2/F3` 被引擎当控制字符就是典型例子（换字形也救不了，因为判断发生在解码之后、绘制之前）。见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) §3。
* 何时更合适：只想快速出一版、游戏又不允许改 exe 时。

### 3.5 免封包（不改 `.ypf`，直接放目录）

* 做法（Dir-A 的逆向文章《[YU-RIS] 免封包处理》）：改 `ysbin\yscfg.ybn` 里的 `filePriorityRelease`（0→1），让引擎优先读**目录里的文件**，然后把改好的 `ystNNNNN.ybn` 直接丢进 `ysbin\`。
* 本作实测（只读检查，`D:\ysbin\yscfg.ybn`，`YSCF ver 555`）：`filePriorityDev=1`、`filePriorityDebug=1`、**`filePriorityRelease=0`** → 默认**不**读目录文件。要走这条路得先改 `yscfg.ybn`，而它本身在包里（先有鸡还是先有蛋），所以**本工具链选择重新封包是更稳的做法**。
* 何时更合适：目标游戏恰好 `filePriorityRelease=1`，或者你能让引擎读到目录里那份 `yscfg.ybn` —— 那样补丁体积可以小很多。

### 3.6 本工具链补上的那一段（公开工具都没有）

| 问题 | 症状 | 公开工具 | 本工具链 |
| --- | --- | --- | --- |
| 4 个汉字被当控制字符（`镳` `锺` `矧` `矬`） | 吞字 / 强制翻页 / 停下等点击 | 无处理 | `check_glossary.py --lines` 报错（契约见 [glossary/STYLE_GUIDE.md](../glossary/STYLE_GUIDE.md) §4.4），`verify_cn_pack.py` 第 [8] 项 gate |
| ruby 符号 | 散文里写 `《》`，引擎按 ruby 标记解析并报 `ルビ記述エラーです。`、拒绝进场景 | 无处理 | 译文改用 `〈〉`，`check_glossary.py` 的 ruby 解析器拦截；引擎侧定界符由 `transcode_yuris_scripts.py` 一并重新编码，回归测试 `test_ruby_check.py` |
| label 名被转码 | 引擎报「ラベル … が見つかりませんでした」 | 无处理 | 转码白名单（只转显示文本，不转标识符） |
| 字重/字号不合适 | 字太粗、溢出对话框 | 无（多数人硬着头皮玩） | `tune_dialogue.py` / `install_glow_sans.py` + 离屏预览 |
| 打包后不知道有没有坏 | 进游戏才发现 | 无 | `verify_cn_pack.py` 8 项校验 |

---

## 4. 什么时候用哪个

| 你的目标 | 推荐路线 |
| --- | --- |
| 自己玩，看懂剧情 | A（Textractor 类挂钩）+ 机翻 |
| 只想把译文整理成可校对工程，还没有补丁 | Translator++ / VNTextPatch / SExtractor 做抽取与工程管理 |
| 出一个**可分发的中文补丁**，引擎允许改 exe | **本工具链（B + C：引擎汉字化）** |
| 出补丁但不许改 exe | 3.4 JIS 替换 / 映射字体；能吃下 3.6 的坑就行 |
| 目标游戏 `filePriorityRelease=1` | 3.5 免封包，补丁只需放几个 `.ybn`，最省事 |
| 想少写代码、只要结果 | 先跑 `YURIS_TOOLS` 流程；它到不了的地方（封包、字体、控制字节）再切回本工具链 |
| 下一个 YU-RIS 游戏，想少逆向 | 先读 `Notes.txt`（格式）＋ 官方手册（语法，见 §6），再决定自研还是套用 |

---

## 5. 为什么本项目还要自研

1. **公开工具都停在"文本层面"**。抽文本这个动作确实被解决得很好了；但从"文本里是中文"到"游戏里正确显示中文"之间那段（编码、字符集、字体表、前导字节表、字重字号、控制字节、ruby 语法、label 名），公开工具基本没有实现。
2. **我们需要可复现的校验，而不是"进游戏碰运气"**。本工具链的 `verify_cn_pack.py` 8 项 + 2 个回归测试 + 逐行 linter，是在两次把游戏玩崩之后加上的；现成工具没有等价物。
3. **需要"补丁不含侵权物"这条硬约束**。工具链刻意切成「补丁器 + 你生成的包」，字体走 OFL 路径，见 [../NOTICE.md](../NOTICE.md)。
4. **需要能被 AI 助手复用的形态**。`.github/skills/yuris-cn-localization/SKILL.md` 把整套流程、红线、校验门压缩成 agent 可直接执行的步骤——这是现成 GUI 工具给不了的（它们需要人点鼠标）。

反过来说，如果你的需求正好落在 §4 表格的前两行，**不必用本工具链**——那是一套为了"可分发的中文补丁"而写的重装备。

---

## 6. 官方渠道（yu-ris.net）

已核实（2026 年核实，页面为 Shift-JIS，需按 CP932 解码）：

* **引擎仍在维护**：下载页有 **YU-RIS Beta4.8 ver 0.495/0.31，[2025/12/31]**（「YU-RIS本体＋ERISサンプルスクリプト」，24.7 MB，MD5 `37E0C47A5884D252E4F7C846A0107FAB`），以及 Beta4.7、更老的 `YSDhk ver 0.405`（文本/脚本转换，依赖 Excel）、`HideyuriViewer`（素材预览）。
* **名词对应**：**YU-RIS = 引擎本体，ERIS = 脚本层**。本作脚本目录 `data\script\eris\*.yst`（`es_text.yst`、`es_charname.yst`……）就是 ERIS 的系统脚本。
* **官方手册就是本工具链逆向出来的那套语法的权威文档**：ERIS マニュアル → `命令一覧` / `基本文法` / `●テキスト命令`（`\C` `\R` `\P` `\AC` `\AR` `\AP` `\TC` `\TS` `\TX.ICON.XYAUTO`）/ `定義ファイル` / `キー割り当て用文字一覧`。抽查 `\R` 确认为「改行命令」的逐命令详解。
  → **建议**：做下一个 YU-RIS 游戏时，先在手册里查命令语义，再对着脚本看，比从零逆向快得多。
* **许可（`YU-RIS/ERIS ライセンス ver1.2 [2014/11/07]`）**：无作者支持时**同人、商业均免费**，条件只有一条免责声明；商业需**事前邮件报备** + 署名「スクリプトエンジン YU-RIS」/「ScriptEngine YU-RIS」；作者 穂乃井たくみ（FIRSTIA），**闭源，不公开源码**。
  → 注意区分：这份许可管的是「**用引擎做你自己的作品**」。它不是、也不可能是「改写别人作品并分发」的授权——那属于版权方（例：CLOCKUP）与二次创作的问题，见 [../NOTICE.md](../NOTICE.md) §4/§6。

---

## 7. 核实状态

| 结论 | 依据 | 状态 |
| --- | --- | --- |
| GARbro 支持 `.ypf` / `.ycg` | `ArcFormats/YuRis/*.cs` | 已核实代码 |
| Textractor 有 YU-RIS 专用挂钩 | `texthook/engine/engine.h:158` | 已核实代码 |
| VNTextPatch 支持 YU-RIS 且附格式文档 | `Scripts/Yuris/`（7 个文件） | 已核实代码 |
| Translator++ 引擎表含 YU-RIS | 官方 README 引擎表 | 已核实文档 |
| SExtractor 支持 Yu-ris | README 引擎列表 + BIN 参数说明 | 已核实文档 |
| YURIS_TOOLS 流程与封包现状 | README | 已核实文档 |
| 官方站/手册/许可/Beta4.8 | yu-ris.net（按 CP932 解码） | 已核实页面 |
| 本作 `filePriorityRelease=0` | 解析 `D:\ysbin\yscfg.ybn` | 已实测 |
| `yuri` 能替代本工具链的注入步骤 | README（有编译器） | **未实测** |
| Translator++ 打开本作的实际效果 | — | **未实测** |
| LunaTranslator / LunaHook 的 YU-RIS 支持 | 未逐条核实 | **未核实** |
