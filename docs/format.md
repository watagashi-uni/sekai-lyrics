# 数据格式

## `lyrics.json`

这是播放所需的数据，也是 `playback/<musicId>.<hash>.json` 的原始文件。两者字节完全相同。

| 字段 | 含义 |
| --- | --- |
| `musicId` | master 的音乐 ID |
| `duration` | 参考游戏音频时长，单位秒 |
| `vocalId` | 参考 musicVocal ID，部分来源仅有 `assetbundle` |
| `assetbundle` | 参考音频资源名，可能为空 |
| `format` | `bilingual_json` 或 `lrc` |
| `lines` | 双语 JSON 模式的播放行 |
| `lrc` / `translationLrc` | LRC 模式的原文／译文 |
| `wordLines` | LRC 模式的逐字增强行，`cueStart` 指向原始 LRC 时间 |
| `rubyLines` | LRC 模式的可选注音行，通过 `cueStart` 和 `text` 对应原始 LRC 行 |
| `romajiLines` | LRC 模式的可选罗马音行 `{ cueStart, text, romaji }`，与 `rubyLines` 一样对应原始 LRC 行 |
| `performers` | `performerId` 与显示名称的对应表 |
| `credits` | 已保存的译者等署名 |
| `sources` | `[来源URL, 许可名, 许可URL]` 数组；更详细的来源见 `sources.json` |

### 播放行与逐字单元

每行包含 `start`、`end`（秒）、`text`、可选的 `translation`、`segments`、`performerIds` 和 `words`。

`words` 中每项为：

```json
{"from":0,"to":1,"start":10.2,"end":10.5}
```

- `from`、`to` 是 `text` 的 **UTF-16 字符串偏移**，范围左闭右开，可直接用 JavaScript `text.slice(from, to)`。
- 时间为绝对游戏音频时间，不是相对于句首的偏移。
- 零时长单元保留为在 `start` 瞬间完成高亮。字间停顿、原始时间重叠不应被平均化。
- 标点、空白等未被单元覆盖的部分仍须显示，不能只拼接 `words` 而丢掉这些文字。
- 某个单元可能是多个字组成的词或短语，不应自行增加不存在的分字时间。
- 没有 `words` 或数组为空时，整行使用逐句高亮。

`segments` 含 `text` 和 `performerIds`；`performers` 提供名字。行上的 `performerIds` 补充行级标记。不要把同一歌曲中一个版本的分唱标记套到另一版本。

### ふりがな

双语 JSON 在播放行中使用可选的 `ruby` 数组。LRC 模式在 `rubyLines` 中保存 `{ cueStart, text, ruby }`，在应用逐字时间轴之前匹配原始 LRC 行。每项为 `{ from, to, reading }`，沿用逐字单元的 UTF-16 偏移，标记 `text` 的读音范围。

### 罗马音

双语 JSON 的播放行带可选的 `romaji` 字符串；LRC 模式使用 `romajiLines`。罗马音由 `scripts/add-romaji.py` 生成：有注音的部分按注音读，其余按 Janome 词典读，助词 は/へ/を 读作 wa/e/o，词与词之间以空格分开。纯英文或符号的行，以及含有词典读不出的汉字的行，不带罗马音。这些都是新增字段，不认识它们的播放器会直接忽略。

注音字段可以缺省，资源仍使用 `v: 1` 索引及现有 `format`。旧播放器会忽略注音字段，普通 LRC 文件保持原格式。注音来自原项目已有读音，可对应到播放文字时才附加。

## LRC

`game.lrc` 和 `game.zh-CN.lrc` 使用 `[mm:ss.mmm]文本`。一行可以有多个时间标签，同一时间也可能有多行。

译文按原文行对应：`game.zh-CN.lrc` 的每一行都使用它所翻译的那一行原文的时间标签，同一个时间标签最多一行译文。没有对应译文行的原文行就是没有译文，可能是：

- 这一句本来就没有译文（拟声词、重复的衬词、来源未翻译的句子、被截断的残行）；
- 一句译文对应几行原文，但中文语序使它无法在行间拆开，这时整句只放在这几行中的第一行。

不要把一行译文延续显示到后面没有译文的原文行。

`game.enhanced.lrc` 采用成对内联标签：

```text
[00:10.200]<00:10.200>あ<00:10.500><00:10.700>い<00:11.000>
```

相邻的结束与开始标签可能相同；存在停顿时会不同。无逐字轴的行只有普通行时间标签。不要用“只有开始标签”的解析器直接套用此文件。

LRC 基于保留的来源行，双语 JSON 基于原项目行，分句、拟声词和注释可能不同。前端应以 `lyrics.json` 的 `format` 选择主显示内容，不要用 LRC 覆盖双语 JSON 的显示修正。

## `game.bilingual.json`

保留原项目行的 `japanese`、`zh-CN`、分唱、`ruby` 注音，以及 `start`／`end`。如存在 `display_text`、`display_japanese`、`display_zh-CN` 或 `display_segments`，播放时优先使用这些字段。`lyrics.json` 已应用这些显示修正，接入方通常无需再次处理。

本文件的 `index` 是原项目行引用，补充的来源行可能为 `null`。不要以连续数组下标推断音频中的完整句子顺序。

罗马音来源优先级：`romaji.sekaipedia.json` 保存可复用的人工罗马音输入；按 NFKC、去空白及 Unicode 标点后的全文严格匹配，优先采用，保留原大小写、空格和标点。输入由 `import-sekaipedia-romaji.py <只读仓库目录>` 提取，排除对方报告的零基 `heuristic_lines`，冲突读音不采用。无法可靠切分、文字不同或无来源的行沿用 Janome＋注音生成；不按字数比例切分。重复句按实际文字匹配。纯英文、符号行不添加。

双语行的 `romajiSource`、LRC `romajiLines[].source` 为 `sekaipedia`（人工来源）、`reviewed`（复核修正）或 `generated`（自动生成）。人工输入记录页面、转取仓库及提交号，许可为 CC BY-SA 4.0；既有文字来源的 oldid 不被当作此次抓取罗马音的修订号。重新运行 `add-romaji.py` 不覆盖人工输入，内容相同不重写。

可选 `readings.reviewed.json` 保存复核日期、来源和 `lines: [{text, ruby, romaji?}]`。`ruby` 使用同样的 UTF-16 范围。两个生成脚本均优先采用文字完全一致的复核项，避免歌曲的特殊读音被上游普通词典读音覆盖。没有复核罗马音的行仍走既有的人工来源／自动生成流程；修改歌词文字后必须同步复核，不能模糊套用。

### LRC 逐句结束时间

可选 `lineTimings: [{cueStart,text,start,end,source}]` 给没有逐字轴的行补充结束时间。按原始 cueStart＋text 匹配，优先级低于 wordLines。旧客户端忽略此字段，仍按下一行开始时间结束；不向普通 LRC 硬塞结束标签。来源与核对方法在 sources.json 中逐行记录。

### 多演唱版本（可选扩展）

顶层继续代表既有默认版本，`versions` 保存其它版本，索引仍为 `v:1`。同一首歌的所有演唱版本使用同一条伴奏，时间轴完全相同，区别在于谁唱哪一行，个别版本还有少数行歌词不同（例如 57 号バーチャルシンガー版的应援喊名）。因此附加版本**不保存时间或逐字轴**，只保存歌手和经复核的不同歌词：每项包含 `vocalId`、`assetbundle`、`duration`（该版本音频长度）、`performers`、`source`（A/B/C/D）、`alignmentStatus` 和 `singers`。

`singers` 每项为 `{row, segments?, performerIds?, text?, translation?, romaji?}`，`row` 是默认版本的零基播放行（双语 lines 数组；LRC 则所有非空行的时间标签展开后，按原始 cueStart 稳定排序，不去重，空白时间标签不占下标），按 row 递增、每行至多一项。`segments` 拼接后等于该行显示的文字。`text`／`translation`／`romaji` 只出现在经复核、该版本确实唱了不同歌词的行（来源 `lyrics/<id>/versions.reviewed.json`）：这一行显示版本自己的文字、译文与罗马音，不使用默认行的注音和逐字轴（文字偏移不再对应），起止时间仍用默认行。没有列出的行在该版本中没有分唱信息；来源 D 及部分覆盖（`partial_*`）的版本可能只有部分行或没有行。播放时文字、译文、注音、罗马音、逐字轴与起止时间一律取默认版本，只把默认行的 `segments`／`performerIds` 换成该版本的（以及上述个别行的文字）。

```json
{"vocalId":465,"assetbundle":"an_0002_01","duration":116,"performers":[{"performerId":"歌唱者-23","name":"鏡音レン","characterId":23},{"performerId":"歌唱者-26","name":"KAITO","characterId":26}],"source":"A","alignmentStatus":"success","singers":[{"row":0,"segments":[{"text":"さあ 眠眠打破","performerIds":["歌唱者-23"]}]}]}
```

示例节选歌曲 2 的一个附加版本，省略后续行。所有 performers 的游戏角色附数字 characterId；外部歌手的 characterId 为 null；能对应官方 master 时另附 outsideCharacterId，不猜游戏 ID。版本来源与缺行情况记录在 sources.json；partial_alignment 仍表示部分覆盖，不能声称全曲完整。
