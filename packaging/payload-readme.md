# payload — 补丁器要用的数据

这个目录是**发行包**的一部分（不在工具链仓库里版本化）。`install_cn_patch.exe`
把这里的一切当作只读输入：`manifest.json` 说"要用哪些文件、期望什么结果"，
校验不过就停下，不写任何东西到游戏目录。

| 路径 | 是什么 | 大小（大约） |
| --- | --- | --- |
| `manifest.json` | 清单：所有文件的 SHA-256、重建期望值、exe 补丁参数、安装路径 | 十几 KB |
| `tools/*.py` | 工具链源码（`build_cn_pack.py` 等）。冻结版 exe 不需要它们，留着给"源码模式"用 | 350 KB |
| `workpack/lines.tsv` | 译文表：每行的 id、原文、译文。重建的输入 | 3.0 MB |
| `workpack/usages.tsv` | 每个 id 出现在哪个脚本的第几行，用于定位替换点 | 1.5 MB |
| `fonts/GlowSansSC-Normal-Light.otf` | 上游 Glow Sans SC 字体（OFL 1.1）。安装时改名+改行距后注册到系统 | 9.3 MB |
| `fonts/OFL.txt` | 字体许可证全文（OFL 要求随字体分发） | 4.4 KB |
| `yuris_decompiler/yurislib/` | 读写 YU-RIS 脚本格式的库（MIT，© 2025 lipsum）。构建路径需要它 | 143 KB |
| `yuris_decompiler/LICENSE` | 上面那个库的 MIT 许可证 | 1 KB |

## 为什么 workpack 里有未翻译的日文原文

`lines.tsv` 的每一行都要参与重建：译文行用译文，未翻译行**必须**回填原文，
否则那一行在重新打包后会变成空串。所以这份表里含未翻译的日文原文
（它们是重建所必需的中间数据，不会以原文形式出现在任何输出文件里——
输出一定是按 CP936 重编码后的脚本内容）。这一点在 NOTICE.md §4 的
"发布形态"里说明。

## 校验

```bat
install_cn_patch.exe --dry-run        :: 全流程试跑，不写任何文件
install_cn_patch.exe --status         :: 看当前游戏目录的安装状态
```

`manifest.json` 里 `build.expected_sha256` 是**总闸**：重建出的 `update1.ypf`
只要有一个字节与发布件不同就硬失败，所以偷换译文表/工具不会静默产生坏包。
