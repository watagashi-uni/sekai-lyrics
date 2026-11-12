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

## LRC

`game.lrc` 和 `game.zh-CN.lrc` 使用 `[mm:ss.mmm]文本`。一行可以有多个时间标签，同一时间也可能有多行。译文与原文不一定逐行一一对应，译文可能覆盖多个原文行。

`game.enhanced.lrc` 采用成对内联标签：

```text
[00:10.200]<00:10.200>あ<00:10.500><00:10.700>い<00:11.000>
```

相邻的结束与开始标签可能相同；存在停顿时会不同。无逐字轴的行只有普通行时间标签。不要用“只有开始标签”的解析器直接套用此文件。

LRC 基于保留的来源行，双语 JSON 基于原项目行，分句、拟声词和注释可能不同。前端应以 `lyrics.json` 的 `format` 选择主显示内容，不要用 LRC 覆盖双语 JSON 的显示修正。

## `game.bilingual.json`

保留原项目行的 `japanese`、`zh-CN`、分唱、`ruby` 注音，以及 `start`／`end`。如存在 `display_text`、`display_japanese`、`display_zh-CN` 或 `display_segments`，播放时优先使用这些字段。`lyrics.json` 已应用这些显示修正，接入方通常无需再次处理。

本文件的 `index` 是原项目行引用，补充的来源行可能为 `null`。不要以连续数组下标推断音频中的完整句子顺序。
