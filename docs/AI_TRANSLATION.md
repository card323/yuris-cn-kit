# AI 翻译工作流（大模型编排 ＋ 本地小模型逐行翻译）

本文记录一套**已经跑完一遍完整汉化**的 AI 分工方式：**云端大模型（agent）负责编排与验证，本地小模型负责逐行翻译**。
它补的是 [PIPELINE.md](PIPELINE.md) §1 第 5 步「翻译」怎么用 AI 做，不替代任何既有文档。

真实规模（本项目的实测数据，用来给后面的参数定标）：

| 项 | 实测 |
| --- | --- |
| 全量可译行 | 16 308 行（其中 1 592 行含 ruby 注音） |
| 交给本地模型译的场景 | 25 个 `Ｈシーン*`，6 111 行，约 1 小时 GPU 时间 |
| 其中一次可计量运行 | 9 文件 / 2 741 行 / 297 次请求 / prompt 180 万 token / 生成 6.9 万 token |
| 吞吐 | 生成 **48.5 tok/s**，prefill 约 18 200 tok/s |
| 译完之后的门禁 | `check_glossary` **0 error**；构建 8 项校验全绿 |

---

## 0. 本文档的保质期

这份文档有一半会过期，另一半不会。判据是**模型为什么会错**：

| 类型 | 例子 | 会怎么过期 |
| --- | --- | --- |
| **约定不可知**——不在任何预训练语料里，模型再强也只能猜或问你 | GBK 禁字表、`《》` 是 ruby 定界符、`＃` 是语音标记、说话人前缀是引擎语法、空行＝保留日文、宽度预算、术语表、拟声音节表 | **不会过期**。必须由人写进提示词和校验器（§3 §5 §7 §12） |
| **能力缺口**——模型不够聪明 | 旁白整句抄回日文、给假名写的自称随手编个汉字、译文文笔平 | **会缩小**：变强后 §10 里这几行会自己消失，对应的提示词条款和校验条款**可以删**（§5 §10 §13） |
| **测量与基础设施**——当年的现场条件 | RTX 4070 12 GB、48.5 tok/s、`num_ctx 16384`、`repeat_penalty=1.0`、Q4_K_M 7 GB | **先过期**。这些是决策时的**证据**，不是处方；留着是为了让后人能复核（§4 §6 §9 §11） |
| **编排纪律**——踩的是流程而不是模型 | 干跑先行、可续跑、空跑也要有证据、报告用绝对行号、度量先于信任 | **不会过期**：它们是**流程 bug**。`--translation-dir` 找不到文件却退出 0，换什么模型都在那儿等着你（§7 §8） |

用法就是一句话：**换模型/换显卡时，重测 §4 §6 §9 §11 里的数字，其余部分照用。**

什么时候该回来改这份文档：

* **换了模型**（换基底或换量化）→ 重跑 §11 的骨架。若 §10 里「能力缺口」那几行不再复现，就把对应的提示词条款和校验条款删掉——留着只会让 prompt 变长、变慢、更容易把模型的注意力挤掉。
* **显存 ≥ 24 GB** → §4 的「严格串行」可以放宽，但仍要先量一次显存曲线再决定并发数，别凭容量猜。
* **Ollama 改了默认采样值**（尤其 `repeat_penalty`）→ §6 那张表要重新确认一遍。
* **换引擎/换作品** → §1 §5 §12 里的引擎常识全部作废，重新走 [ENGINE_NOTES.md](ENGINE_NOTES.md) 的定位流程；但 §7 §8 照用。

最后一条与模型无关的结论值得单独说：把**不可信的生成器**接进**可信的构建流水线**时，真正起作用的是校验器与构建同源、修复按成本分级、兜底必须是安全默认（修不好就留空）、度量先于信任。**验证的成本不会因为模型变聪明而降到零，它只会从"救火"变成"保险"**——而且你会因为敢让它无人值守而把保险买得更多。

---

## 1. 分工判据：按「每个 token 需要多少上下文」切

| | 谁做 | 干什么 | 活的形状 |
| --- | --- | --- | --- |
| **编排者** | 云端大模型（agent；本项目里就是 VS Code 里的 Copilot/DeepSeek 系模型） | 读 20+ 个工具脚本、解包抽文本、生成工作包、写校验脚本、发起/恢复批量翻译、审计 diff、打包安装、写文档 | 上下文长、调用次数少 |
| **译者** | 本地小模型（Ollama，12B Q4） | 日文 N 行 → 中文 N 行 | 上下文短、调用次数上千 |

一句话判据：**要靠长上下文才能做对的事，交给云端大模型；上下文很短但要重复上千次的事，交给本地小模型。**

三个附带好处：

* 文本不出本机——18+ 内容与版权文本不该送进任何第三方 API。
* 批量翻译不消耗云 token；跑一整晚也不心疼。
* 本地模型可以固定 `seed`，产物可复现、可回滚。

一个必须接受的后果：因为文本不出本机，**大模型看不到译文**。所以编排者只能靠**确定性校验器的输出**判断译文好坏（§7、§9）。这不是缺陷，而是这套分工的核心约束——也正因如此，§7 才是全文最重要的部分。

---

## 2. 什么时候用哪条路

| 路线 | 适合 | 代价 / 风险 |
| --- | --- | --- |
| 人工翻译 | 几千行以内、要出版级文笔 | 时间线性增长；几万行不现实 |
| 云端大模型直译 | 短篇、可以外发文本 | 文本离开本机；长文按 token 付费；模型拒译 18+ 内容 |
| **本地小模型批量 ＋ 大模型编排** | 上万行、文本不能外发、可接受"逐行机译质量 ＋ 事后筛检" | 需要一块能装下模型的显卡；模型指令遵循弱，**必须外挂校验**（§7） |
| 机翻 API ＋ 人工后编 | 已经有译者，只想省打字 | 仍要有人逐行过；本项目的 `lines.tsv` 就是这种后编界面 |

**显卡底线**：模型权重要装进显存且留出 KV cache。12 GB 卡上 12B Q4_K_M 可用，8B 更宽裕；同尺寸的 **F16 权重（例：7.6B 的 F16 占 14.2 GB）装不下，别选**。

---

## 3. 三条硬性要求（不满足就别开工）

1. **引擎的规矩必须写进提示词**。模型不知道你的产物是 GBK、不知道 `《》` 会被引擎当 ruby 定界符、不知道促音该丢、不知道说话人前缀是语法。这些规则不写进 system prompt，后面就得逐条人工擦屁股（§5）。
2. **模型输出必须外挂确定性校验器**，而且要和构建阶段用**同一份**校验器（本项目是 `check_glossary.py`）。模型自评不是校验。
3. **必须能续跑**。本地 ollama 跑一小时一定会打嗝（500、连接断、机器休眠）。要求：文件级断点（`.part` 文件）、已完成文件跳过、日志可追、外层可以反复重启内层而不重做。

---

## 4. 硬件与显存纪律

### 4.1 严格串行

> 每个并发请求都要独占一个 context slot；12 B 模型 × 16 K 上下文，两个 slot 在 12 GB 卡上放不下。

所以：**一次一个请求**，跑之前先问 ollama 有没有别的模型占着显存，跑完可以主动卸载。

```powershell
curl.exe -s http://127.0.0.1:11434/api/ps     # 现在谁在显存里
curl.exe -s http://127.0.0.1:11434/api/tags   # 本地有哪些模型
```

| 参数 | 实测取值 | 为什么 |
| --- | --- | --- |
| `num_ctx` | 16384 | 一个 chunk 的 prompt ＋ 术语表 ＋ 输出预算要放得下；再大就吃掉 KV cache 的余量 |
| chunk 大小 | **30 行 / 1200 字符** | 坏一块只重做一块；chunk 边界永远是行边界，所以可以断点续跑 |
| `keep_alive` | `10m` | 别让模型在 chunk 之间被换出换进（每次重载 2–20 s） |
| 最小空闲显存 | 400 MiB，低于就停 | 与其赌一把，不如停下来让人看一眼 |
| 请求超时 | 600 s | 本地 12B 在 chunk 上的正常耗时是 10–25 s，留足余量 |
| 服务端 5xx | 重试 4 次，退避 20/40/60 s | 本地服务偶发 500，不值得整批失败 |

### 4.2 两个上下文开关，别搞混

* **请求内 `options.num_ctx`**（推荐）：只影响这一次调用，可复现，换机器不用改环境。本项目用这条。
* **服务端全局**：`OLLAMA_CONTEXT_LENGTH`（例 `32768`）等环境变量只在 ollama 服务启动时读一次，所以要 `setx` 之后**重启 ollama**。它管的是"没显式指定时用多大上下文"，用来兜底可以，用来当唯一真相会和脚本里的参数打架。

### 4.3 选型实验：先用一小段做 3 次对照

别拿整篇小说去试模型。用一段几百字的真实文本，**同一段落独立调用 3 次**，比较：

* `gen_tok_s`（生成速度）、`prefill_s`（首字延迟）、`load_s`（冷加载）
* 是否漏内容（脚注、数字、专有名词）、是否自己加小标题、是否输出行数漂移
* 是否拒译（审查模型在 18+ 文本上会软化措辞甚至拒绝）

本项目结论：**去审查（abliterated / uncensored）的本地模型是这类文本的前提**；代价是这类模型指令遵循更弱，所以 §7 的校验更不可省。

---

## 5. 提示词：把引擎的规矩翻译成模型能懂的规矩

只留下**这一层真正需要的**条款（写作层面的规范见 [TRANSLATION_RULES.md](TRANSLATION_RULES.md)）：

| 条款 | 为什么必须有 |
| --- | --- |
| 输入 N 行 → 输出恰好 N 行，不编号、不抄原文、不空行、不加说明 | 行数漂移是所有后续步骤的根，必须最先钉死 |
| 说话人前缀照抄日文，只译标记里面的内容 | 前缀是引擎语法，译了就名牌空白 |
| ruby `≪汉字／假名≫` 删标记、只译里面的字 | 产物里残留 `≪≫／` 会直接崩游戏 |
| 正文禁 `《》`，书名号用 `〈〉` | `《》` 是引擎的 ruby 定界符 |
| 禁 4 个汉字（`镳` `锺` `矧` `矬`）、禁 `・` `々` `ヶ` 长音符半角片假名 | 这些字的 GBK 字节被引擎当控制符，会吞字/强制翻页 |
| 标点全用全角，省略号 `……` 两个、破折号 `——` 两个 | 排版与自动换行的前提 |
| 呻吟/拟声的**逐音节对照表** + 促音 `っ` 不写 + 同字最多连写 12 个、其余用 `～` 收尾 | 不写这张表，模型会写"法、昂、一"这类同音错字，或输出 25 个连续"啊" |
| `＃` 与 `♪` 原样保留，原文有几个就写几个 | `＃` 是语音分段的标记，模型合并从句时会吃掉它 |
| 术语表**全量注入** system prompt，同一事物全篇同一个词 | 术语一致性的唯一抓手；大表会挤掉正文，所以术语表要精炼 |
| 和文漢字 → 中文对照（`本当に`→真的、`大丈夫`→没事吧） | 汉字词最容易被照抄进译文 |
| **旁白也要译**，不许把原文原样抄回来 | 不写这条，模型会只译引号里的台词、把旁白整句抄成日文（实测 35 行里 10 行旁白这样废掉） |
| **假名写的自称/昵称也要收进术语表**（例：某角色的自称写成假名，项目定的译名是一个汉字） | 不说的话模型会给它随手挑个同音汉字。实测：不写进术语表时那一行的自称被编成了另一个字；写进术语表后稳定输出指定的那个字（§10 有同一行的记录） |
| 长度不超过原文 20%、宽度预算 | 引擎会自动换行，但太长的行排版难看（[TROUBLESHOOTING.md](TROUBLESHOOTING.md) §8） |

可复用的片段（示意，实际 system prompt 约 3 KB）：

```
【输出格式（最重要）】
- 输入 N 行，你必须输出恰好 N 行，顺序与输入完全一致，一行对一行。
- 不要输出编号、不要抄原文、不要空行、不要任何说明或注释、不要合并或拆分行。

【全部要译】
- 旁白、描写句、心理描写也要译成中文，绝不允许把原文原样抄回来。只有说话人前缀照抄。

【说话人前缀必须原样保留】
- 形如 名字「台词」、名字『台词』、名字（内心独白）的行：前缀的日文名字和标记符号一律照抄原文，
  不翻译，只翻译标记里面的内容。收尾标记与开头配对：「」『』（）。

【字符集与标点（产物是 GBK，写错会崩游戏）】
- 不要出现 々、ヶ、长音符 ー、半角片假名，也不要残留任何假名（假名说明有词没翻）。
- 这四个汉字绝对不能出现（GBK 字节会被引擎当控制符，会吞字或强制翻页）：镳、锺、矧、矬。
- 书名、标题用 〈〉，绝对不要用《》（《》是引擎的 ruby 定界符）。
- 原文里的 ＃ 和 ♪ 原样保留，原句有几个 ＃，译文就必须有几个 ＃。
- 译文长度尽量与原文相当，不要超出原文 20% 以上。

【术语表】{glossary}
```

---

## 6. 采样参数与确定性

| 参数 | 取值 | 为什么 |
| --- | --- | --- |
| `temperature` | **0.3** | 再高开始自由发挥（改专名、丢标记）；再低没必要，0 也不等于确定 |
| `repeat_penalty` | **1.0**（关掉） | Ollama 默认 1.1 会惩罚"重复"——而本任务每行都在重复说话人前缀、术语、`＃`。实测 1.1 会**丢前缀、坏字形** |
| `seed` | 固定 0，重试时 `+7919` | 可复现；重试必须换 seed，否则拿到同一个答案 |
| `num_predict` | chunk：`max(1024, 输入字数×3)`；单行修复：512 | 翻译的输出体积≈输入，预算必须按输入长度给，给死值会在长 chunk 上截断 |
| `think` | `false` | 这是"逐行转写"不是"推理题"；开启思考会吃掉输出预算并把结果挤成空 |
| `stream` | `false` | 一次拿全，`done_reason` 才可判 |

**最反直觉的一条**：`temperature 0.3` ＋ 同一个 prompt ＋ 同一个 seed ＝ **稳定复现同一个错误**。
所以"重发一次试试"不会有任何改变；重试必须把**上一次的输出**和**错在哪**（中文写的错因清单）一起回传：

```python
messages = messages[:2] + [
    {"role": "assistant", "content": previous_reply},
    {"role": "user", "content": f"你上一次的输出有错，请重新输出整整 {n} 行（不要编号），"
                                f"并修正以下问题：\n- " + "\n- ".join(problems[:8])},
]
```

另外，收到 `done_reason == "length"` 时**不要当成译文差**：那只是一句话没写完。正确做法是保留已完成的前缀（丢掉可能被截断的最后一行），**只请求剩余的部分**——比整块重来省一次请求。

---

## 7. 不信模型：确定性校验 ＋ 分级修复

```
模型输出
  │
  ├─ done_reason == "length" ────▶ 保留前缀，只请求剩余尾部
  ├─ 行数 ≠ 源行数 ──────────────▶ 整块重试（行数漂移只有新回复能救）
  └─ 行数一致
       ├─ ① 确定性字形修复（OpenCC t2s ＋ 新旧字体表）—— 能不改模型就不改模型
       ├─ ② 逐行硬校验：前缀 verbatim / ruby / 禁字 / 残留假名 / 术语 / 宽度
       │     └─ 坏行 ≤ 1/3 ──▶ 单行重译（约 1.5–3 s）而不是整块重试（约 18 s）
       └─ ③ 单行重译仍失败 ──▶ 写空（空 = 构建时保留日文），记进 metrics 的 problems
```

六条可复用的规矩：

1. **校验器就是构建时那一份**（`check_glossary.py` 的 `check_line`）。本地模型和人工译文走同一道门，没有特权。
2. **修复成本要分级**：整块重试 ~18 s vs 单行重译 ~1.5–3 s（本项目代码注释记 1.5 s，2025 版骨架实测约 2.5 s）。判据：坏行数 × 3 ≤ chunk 行数时走单行，否则整块重试。
3. **采纳新结果要有判据**：重译只有在**可测量地更好**（硬错误更少）时才替换，坏回复永远不该让结果变差。
4. **兜底必须是安全的**：修不好的行留空 = 保留日文原文（[PIPELINE.md](PIPELINE.md) §2.4 的约定），所以一个 90% 完成的批次也能出一个不崩、不乱码的游戏。
5. **重试提示语本身也要被校验器拉黑**。被要求"修正以下问题"的模型，偶尔会把**这句话**当成译文交回来；本项目真的发布过一行 `上一次译文有错：正文里残留了日文假名…`。凡是提示语里用来"谈论这一行"的句子，都必须在校验器里整句拒绝（而且这两处清单要同步维护）。
6. **采纳第二个回复前要比较**：把上一版草稿和错因一起发回去，模型可能答得更差。只采纳"能过校验器、且不比原来差"的那个；如果新版更差而旧版还救得回来，就留旧版。

---

## 8. 编排者（agent）的六条纪律

这一节是这套工作流里最值钱的部分：**大模型的价值不在"翻得好"，而在"改得可验证、可回滚、可复现"。**

1. **破坏性操作一律两段式**：先干跑/预览，看清楚再 `--apply`。本项目所有改文件的工具都自带这条（`merge_translation.py` 默认干跑、`patch_yuris_charset.py` 默认 dry run）。
2. **改动前留回滚点**：`.bak` 只是第一步，还要留**能一键回到上一个发布态**的整包（本项目留了 `update1.ypf.noH` ＋ `_rollback_noH\`）。
3. **变更前先预测变更集，变更后逐文件哈希比对**，并断言"多出来的变动 = 空列表"。例：

   ```
   预期：yst00183/188/201（共用一行改到 3 个非 H 场景）+ yst00215/216/217/219/232（5 个 H 场景）
   实测：changed = 8 个，unexpected = []
   ```
4. **干跑产物与正式产物必须哈希相等**。`merge --out _dry.tsv` 与 `merge --apply` 后比对：相等才说明"你看过的就是要发布的"。
5. **门禁命令固定且可复现**：每次构建都用同一条命令（[PIPELINE.md](PIPELINE.md) §2.8），不要"这次少传一个参数试试"。
6. **不能自检的部分明确交接给人**。例：agent 读不了截图，就无法替你判断"游戏里这一行排版好不好看"。把它列成待办交给用户，而不是含糊地说"应该没问题"。

另外两条血泪：

* **空跑也要有证据**。本项目踩过：`merge_translation.py` 没传 `--translation-dir` 时找不到那 25 个文件，**仍然退出码 0**——一次"全绿"的运行其实一行都没检查。凡是"批量成功"，都要打印它到底处理了多少行。
* **同一个 id 可能被多个场景共用**。改一个共用行等于改所有场景的同一行；H 批次的覆盖会**静默改掉非 H 场景已发布的文本**。动共用行之前先查 `workpack\usages.tsv` 的分布，确认要不要统一译法。

---

## 9. 度量与筛检：把 16 308 行缩成 12 行

### 9.1 每次运行都落一份度量

按场景（或按批）记：`lines / requests / prompt_tokens / gen_tokens / prefill_s / gen_s / wall_s / load_s / retries / repairs / term_repairs / rebuilds / simplified / polished / soft / problems`。
本项目存成 `_metrics.json`，一条命令出表（不耗 GPU）：

```
scene                          lines  req   prompt     gen   gen_s     wall retry repair  term   fix  soft  bad
H04　珠夜処女喪失                498   37   231885   14176   291.5    307.4     0     16     3   649    17    2
H08　カノ四肢断裂・生贄プレイ        501   32   194980    7118   146.3    185.4     0      6     0     0    11    2
TOTAL                          2741  297  1800800   69276  1427.2   1715.1     9    161    23   846    94    8
；tokens generated at 48.5 tok/s
```

这张表同时是排错入口：`req` 突然翻倍＝有 chunk 在反复重试；`fix`（确定性字形修复次数）高＝提示词里的简繁/字形条款没写够；`bad` > 0 的行号就是待人工确认的清单。

### 9.2 用统计筛子把人工复核量压到可承受

不可能有人通读 16 308 行。可复用的是**几个便宜的筛子 ＋ 小规模人工过目**：

| 筛子 | 判据 | 本项目结果 |
| --- | --- | --- |
| **长度比** | 新译文/原文 ≥ 1.55 且原文 ≥ 8 字 | 0 条 |
| 长度比（放宽） | ≥ 1.30 | 12 条 → 人工过目 → 确认 **4 条真缺陷**（1 处编造内容、1 处误译、1 处语义丢失、1 处语气降级） |
| 同一 id 多场景一致性 | `usages.tsv` 里同一 id 的译文不一致 | merge 直接报冲突（本项目 6 条 → 统一译法后降到 4 条） |
| 软告警分级 | 校验器的 soft 计数（`[name] [skill] [h] [term]` 等） | 94 条，按类抽看，比逐行读省 10 倍时间 |

要点：**筛子只负责把 16 000 行缩到十几行，判断仍然交给人**。反过来，这十几行里查出来的错，说明筛子选对了。

---

## 10. 真实失败模式（都踩过）

| 症状 | 成因 | 处置 |
| --- | --- | --- |
| 行数比源文多/少 | 模型合并或拆分了行 | 行数锁定校验 → 整块重试（或按行重译） |
| 说话人前缀丢失/被翻译 | `repeat_penalty` 生效、或提示词没说清前缀是语法 | `repeat_penalty=1.0` ＋ 前缀 verbatim 校验 |
| 正文残留假名（`ご` `マ` `チ`）、残留 `ー` | 模型漏译了词尾 | 硬校验 → 单行重译；仍不行留空 |
| 整行是同一个字重复 25 次（`啊×25`） | 长音被"照抄" | 提示词写"同字最多 12 连，其余用 `～`"；硬校验挡住 |
| 旁白/描写句被整句抄回日文（只有台词被译） | 提示词没说"旁白也要译" | 提示词补这条；实测 35 行里 10 行旁白这样废掉，只能逐行重译 |
| 凭空加细节 / 丢主语 | 小模型的自由发挥 | 长度比筛子抓出来 → 单行重译 |
| 假名写的自称被编成同音汉字 | 模型给假名词随手挑了个汉字 | 假名自称/昵称也收进术语表，并靠"同一 id 全篇一致"盯住 |
| 短反问句译反（`いやか？`→"不觉得吗？"） | 短句上下文不足，模型靠猜 | 抽看短行；术语表里把这类"口头语"也收进去 |
| 输出行是提示语本身（`上一次译文有错：…`） | 模型回声：把重试指令当成待译内容 | 校验器把提示语整句拉黑（§7 第 5 条） |
| 同一个 id 的非 H 场景文本被改 | 共用行被 H 批次覆盖 | 改前查 `usages.tsv`；要么统一译法，要么别动 |
| 中途停下来不再继续 | ollama 500 / 机器休眠 | 文件级 `.part` 断点 ＋ 外层重启包装（最多 6 轮，每轮间隔 30 s） |
| 跑到一半显存爆 | 另一个模型还占着、或并发 slot | 跑前查 `api/ps`；一次一个请求；设最小空闲显存阈值 |

---

## 11. 最小可复用骨架

下面的脚本是"模板"：能直接跑（`python -X utf8 skeleton.py 源文件.txt`），要接到别的项目时只需要换 `SYSTEM` 和 `check()`。

> 这份骨架不是"写完没跑过"的示例：它拿本项目真实原文（`Ｈシーン01　….txt`，H 场景批次里的一个文件）的前 35 行跑过，按 20 行分块。结果见代码块后面的实测记录。

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地模型逐块翻译骨架：一次一块；坏块逐行重译；带度量与兜底。

    python -X utf8 skeleton.py <源文件.txt> [--model M] [--out 译文.txt]
输入 N 行 → 输出 N 行（第 N 行 = 第 N 行）；另存 <out>.metrics.json。
本脚本一次跑一个文件，跑整批时包在"重启到完成为止"的外层里（见 §12）。
"""
import argparse, json, re, time, urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:11434/api/chat"
KANA = re.compile(r"[\u3041-\u309f\u30a1-\u30fa\u30fc]")
# 重试提示语一旦被模型当译文交回来，就会被当成正常输出写进产物，所以校验器要整句拉黑。
ECHO = re.compile("上一次译文有错|上一次的输出有错|请只重新输出|请重新输出整整"
                  "|并修正以下问题|这一行要注意")

SYSTEM = """你是日文视觉小说的简体中文译者。把用户给出的日文台词逐行译成简体中文。
【输出格式】输入 N 行，必须输出恰好 N 行，顺序一致；不要编号、不要抄原文、不要空行、不要说明。
【全部要译】旁白、描写句也要译成中文，不许把原文原样抄回来；只有说话人前缀按下一条照抄。
【前缀】形如 名字「台词」的行：说话人前缀照抄日文，只译标记里面的内容；收尾标记与开头配对。
【ruby】≪汉字／假名≫ 是注音：删掉标记，只把里面的字照常译成中文。
【字符集】译文里不得残留任何假名、々、ヶ、长音符；标点用全角；书名号用 〈〉（《》是引擎语法，禁用）。
【拟声】呻吟/拟声按音节写成汉字，且全篇统一（例：ちゅ→啾、ん→嗯；实际项目要把完整对照表写在这里），
        绝不要保留假名，也不要用同音错字（法、昂、一这类）；促音 っ 不写出来。
【术语】人名、假名写的自称都译成中文并全篇一致（例：某自称 → 术语表里定好的那个汉字）。（真项目把整张术语表注入这里）
"""


def ask(messages, options, model, timeout=600):
    body = {"model": model, "stream": False, "think": False, "keep_alive": "10m",
            "options": options, "messages": messages}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        p = json.load(resp)
    return {"text": ((p.get("message") or {}).get("content") or "").strip(),
            "cut": p.get("done_reason") == "length",
            "prompt_tokens": p.get("prompt_eval_count", 0),
            "gen_tokens": p.get("eval_count", 0),
            "gen_s": p.get("eval_duration", 0) / 1e9,
            "wall_s": round(time.perf_counter() - t0, 2)}


def bill(tot, res):
    """重试也要计费，否则度量会骗人（只记最后一次等于漏掉一半成本）。"""
    for k in ("prompt_tokens", "gen_tokens", "gen_s", "wall_s"):
        tot[k] = tot.get(k, 0) + (res.get(k) or 0)
    tot["requests"] = tot.get("requests", 0) + 1
    return tot


def check(src, dst):
    """换成你项目自己的校验器；本项目用的是 check_glossary.check_line。

    检出率就等于这里写了多少条款：少写一条，模型就会从那条缝里漏过去。
    """
    bad = []
    prefix = re.match(r"^([^「『（]*[「『（])", src)
    if prefix and not dst.startswith(prefix.group(1)):
        bad.append("说话人前缀没有照抄：这一行应以 %r 开头" % prefix.group(1))
    if KANA.search(dst):
        bad.append("残留假名或长音符")
    if "《" in dst or "》" in dst:
        bad.append("正文出现《》")
    if dst.count("＃") != src.count("＃") or dst.count("♪") != src.count("♪"):
        bad.append("＃/♪ 的个数与原文不一致（模型丢掉或合并了）")
    try:
        dst.encode("gbk")           # 产物是 GBK：编不进去的字符会崩游戏
    except UnicodeEncodeError as exc:
        bad.append("有字符编不进 GBK：%r" % dst[exc.start])
    if ECHO.search(dst):
        bad.append("把重试提示语当成了译文")
    if re.search(r"(.)\1{23,}", dst):
        bad.append("同一个字连写 24 次以上")
    return bad


def translate_chunk(chunk, model, retries, tot):
    """整块翻译；返回 (译文行, {行号: [问题]}, 需要逐行修的行号)。"""
    user = "\n".join(chunk)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user}]
    opts = {"temperature": 0.3, "repeat_penalty": 1.0, "num_ctx": 16384,
            "num_predict": max(1024, len(user) * 3)}
    for attempt in range(retries + 1):
        opts["seed"] = attempt
        res = ask(messages, opts, model)
        bill(tot, res)
        out = [l for l in res["text"].splitlines() if l.strip()]
        if res["cut"]:
            problems = {"-": "回复被截断：调大 num_predict 或减小 chunk"}
        elif len(out) != len(chunk):
            problems = {"-": "行数不符：要 %d 行，给了 %d 行" % (len(chunk), len(out))}
        else:
            problems = {}
            for i, line in enumerate(out):
                for p in check(chunk[i], line):
                    problems.setdefault(i + 1, []).append(p)
        if not problems:
            return out, {}, set()
        # 同一个 prompt 加同一个 seed 会稳定复现同一个错误：必须把上一次的
        # 输出和"错在哪"一起发回去，光重发没有用（§6）。
        if attempt < retries and "-" not in problems:
            detail = "\n- ".join("第 %d 行：%s" % (i, "；".join(ps))
                                 for i, ps in sorted(problems.items()))
            messages = messages[:2] + [
                {"role": "assistant", "content": res["text"]},
                {"role": "user", "content":
                 "你上一次的输出有错，请重新输出整整 %d 行（不要编号），"
                 "并修正以下问题：\n- %s" % (len(chunk), detail)}]
    if "-" in problems:
        # 行数漂移只有新回复能救，上面已经试够了：整块作废，交给逐行重译
        # （一行一个请求不会被行数漂移影响，代价是行数 × 单行成本）。
        return [], {}, set(range(1, len(chunk) + 1))
    return out, problems, {i for i, _ in problems.items()}


def repair_line(src, previous, problems, model, tot, seed):
    """只重译这一行：整块重试约 18 s，单行约 1.5–3 s，能局部修就别整块重来（§7）。"""
    if not previous:
        previous = "（上一次没有给出可用的译文）"
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": src},
                {"role": "assistant", "content": previous},
                {"role": "user", "content":
                 "这一行要注意：" + "；".join(problems) + "。请只重新输出这一行的译文"
                 "（不要编号，不要输出多行），修正上述问题，其余不变。"}]
    res = ask(messages, {"temperature": 0.3, "repeat_penalty": 1.0, "num_ctx": 16384,
                         "num_predict": 512, "seed": seed}, model)
    bill(tot, res)
    got = [l for l in res["text"].splitlines() if l.strip()]
    return (got[0] if len(got) == 1 else ""), res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--model", default="huihui_ai/gemma-4-abliterated:12b")
    ap.add_argument("--out", default=None)
    ap.add_argument("--chunk-lines", type=int, default=30)
    ap.add_argument("--retries", type=int, default=2)
    a = ap.parse_args()

    src = Path(a.src)
    out_path = Path(a.out or (src.stem + ".zh.txt"))
    lines = src.read_text(encoding="utf-8").splitlines()
    done, rows = [], []
    for start in range(0, len(lines), a.chunk_lines):
        chunk = lines[start:start + a.chunk_lines]
        tot = {}
        out, problems, bad = translate_chunk(chunk, a.model, a.retries, tot)
        filled = (out + [""] * len(chunk))[:len(chunk)]
        for i in sorted(bad):
            for try_no in range(2):
                text, _ = repair_line(chunk[i - 1], filled[i - 1],
                                      problems.get(i) or ["未通过校验"], a.model,
                                      tot, seed=31 + 7 * (start + i) + try_no)
                if text and not check(chunk[i - 1], text):
                    filled[i - 1] = text
                    break
                filled[i - 1] = ""      # 两天都修不好就留空 = 构建时保留日文原文
        done += filled
        blank = [i for i in sorted(bad) if not filled[i - 1]]
        rows.append({"first_line": start + 1, "lines": len(chunk),
                     "requests": tot["requests"], "prompt_tokens": tot["prompt_tokens"],
                     "gen_tokens": tot["gen_tokens"], "gen_s": round(tot["gen_s"], 1),
                     "wall_s": round(tot["wall_s"], 1),
                     # 行号一定要换算成文件里的行号：报告里出现"第 10 行"而文件
                     # 只有 15 行的一块，比不报告还糟。
                     "unresolved": ["%d: %s" % (start + i,
                                                "；".join(problems.get(i) or ["未通过校验"]))
                                    for i in blank]})
        print("%5d-%-5d %3d 行 %2d 次请求 %6d tok %6.1f s  未解决 %d" % (
            start + 1, start + len(chunk), len(chunk), tot["requests"],
            tot["gen_tokens"], tot["wall_s"], len(blank)))

    out_path.write_text("\n".join(done) + "\n", encoding="utf-8")
    gen = sum(r["gen_tokens"] for r in rows)
    sec = sum(r["gen_s"] for r in rows)
    metrics = {"model": a.model, "lines": len(lines), "chunks": rows,
               "gen_tokens": gen, "gen_s": round(sec, 1),
               "gen_tok_s": round(gen / sec, 1) if sec else None,
               "unresolved": [u for r in rows for u in r["unresolved"]]}
    Path(str(out_path) + ".metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    print("%s  %d 行  %s tok/s  未解决 %d" % (
        out_path, len(done), metrics["gen_tok_s"], len(metrics["unresolved"])))


if __name__ == "__main__":
    main()
```

跑整批时把它包一层"重启到完成为止"的包装（本项目：最多 6 轮，每轮间隔 30 s，已完成文件跳过，日志续写），因为一小时以上的本地推理**一定**会在某处中断。

### 实测记录

上面这份骨架（`check()` 里的 7 条硬检查一字未改）拿本项目真实原文跑过：`huihui_ai/gemma-4-abliterated:12b`、RTX 4070 12 GB、`--chunk-lines 20`，源文取 `Ｈシーン01　….txt`（H 场景批次里的一个文件）的前 35 行。同一份脚本**连着跑三次**，三次的数字并排写：

| 块 | 行数 | 请求数 | 生成 tok | 耗时 | 未解决 |
|---|---|---|---|---|---|
| 1-20 | 20 | 1 / 1 / 1 | 543 | 11.8 / 11.8 / 12.2 s | 0 / 0 / 0 |
| 21-35 | 15 | 9 / 11 / 11 | 1152-1229 | 27.8-29.3 s | 2 / 2 / 2 |

整体 47.9-48.4 tok/s。另用独立脚本（不调用 `check()`）重算：35/35 行对齐、`＃`/`♪`/`《》` 计数全部与原文一致、说话人前缀全部照抄、无残留假名、留空行数恰好等于未解决数——三次都是"问题：无"。

* **第 1 块三次一模一样**（1 次请求、约 11.8 s）：块首正是"台词 ＋ 旁白"混排的段落，`SYSTEM` 里【全部要译】那条生效了。把这条删掉再跑，实测 35 行里有 10 行旁白被整句抄回日文。
* **第 2 块每次都卡在同样两行**：整行都是音节的拟声（`んれろっ、ちゅばっ…ずずずぅっ＃` 这种），模型倾向把说话人前缀也改成简体、并顺手吃掉 `＃`。三次都没修好，最后**留空**（= 构建时保留日文原文）。这就是"兜底必须安全"的价值：一条修不好的拟声词不会拖垮整批，也不会把坏行打进成品。
* **拟声对照表给全了会更省**：骨架里只演示 2 对音节，这两行三次全挂；把**完整**对照表写进提示词的另外两轮，未解决数是 1 和 0。样本很小、不当结论，但方向上支持 §5 那句"实际项目要把完整对照表写在这里"。
* **失败原因会漂**：同样是那两行，第 2 轮说"`＃` 个数不对"，第 1、3 轮多一条"前缀也被改了"。所以**判据只能是校验器，不能是"看起来对了"**（§6），报错信息也要写清它到底哪一条不通。
* **报告里的行号必须是文件绝对行号**：那两行是文件第 27、30 行，不是块内第 7、10 行，否则人工复核根本找不到它们。
* **校验器抓不到的也要看**：三次译文里第 21 行都有同一个日式汉字词被整词照抄进中文，7 条硬检查全部放行。所以 §9 的长度比筛子和人工抽检不能省（§13）。

---

## 12. 接到本工具链上

本地模型只写 `translation\userscript\<场景>_中文.txt`，**不碰** `workpack\lines.tsv`；剩下全部走既有工具：

```powershell
# 1) 逐场景骨架（PIPELINE §2.4）——本项目的 H 场景放在子目录
#    translation\userscript\H\ＨシーンNN　….txt → …_中文.txt

# 2) 批量翻译（可中断、可续跑），完事后看度量表
python -X utf8 translate_h_batch.py --only Ｈシーン
python -X utf8 translate_h_batch.py --report

# 3) 门禁：先把译文并进临时表再 lint（这样权威输入不会被污染）
python -X utf8 merge_translation.py --translation-dir translation/userscript/H --only Ｈシーン --out _dry.tsv
python -X utf8 check_glossary.py --lines _dry.tsv

# 4) 正式合并 + 构建 + 8 项校验 + 安装（PIPELINE §2.5 / §2.8）
python -X utf8 merge_translation.py --translation-dir translation/userscript/H --apply
python -X utf8 build_cn_pack.py --workpack workpack --indir D:\ysbin --out build --face "Glow Sans SC" --td-size "M=30x32, NAME=30x32" --install --install-dir "<游戏目录>"
```

* `merge_translation.py` **默认扫 `translation\userscript`（平铺）**；场景放在子目录时必须显式传 `--translation-dir`，否则它一个文件都找不到还照样退出 0。
* `--only <子串>` 可以只处理 `Ｈシーン` 这一批，另外的批次互不干扰。
* 别跳过 §3 第 6 行的门禁：**一个模型读不懂的包，比没有包更糟**。

---

## 13. 局限

* 逐行机译的**文笔**是"通顺但平"，要出版级质量仍需人工润色（本项目走的是"筛子 ＋ 局部重译"而不是全篇重写）。
* 模型看不懂引擎约束时只能靠外挂检查兜住；**校验器覆盖不到的错误（语义偏移、语气降级）只能靠筛子 ＋ 人工过目**（§9.2）。
* 场景连续性有限：一次只给它 30 行，跨行的人称、时态、口吻一致性主要靠术语表和"同一 id 多场景一致"这条规则来保。
* 会话式 agent 的产物**必须落成文件 ＋ 校验证据**才可信：对话里的"我已经翻译好了"不是交付物。
