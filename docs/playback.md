# 静态托管与播放

将 `playback/` 的内容上传到自己的静态资源前缀，例如 `/lyrics/`：

1. 请求 `/lyrics/version.json`，得到 `songs[musicId]`。
2. 请求 `/lyrics/<musicId>.<hash>.json`。
3. 按 `format` 读取 `lines` 或解析 `lrc`。
4. LRC 模式用 `wordLines` 的 `cueStart` 和 `text` 找到对应 LRC 行，将其 `words`、`start`、`end` 合入。译文行按时间标签对应到同一时间的原文行（先按原始 LRC 时间对应，再合入逐字轴的 `start`），每行译文只显示在这一行下；没有对应译文行的原文行不显示译文，不要沿用上一行的译文。
5. 双语 JSON 直接读取每行的可选 `ruby`。LRC 模式用 `rubyLines` 的 `cueStart` 和 `text` 匹配原始 LRC 行，在应用逐字轴的时间偏移之前完成匹配。
6. 根据 `audio.currentTime` 确定活动行。有 `words` 的句子逐字高亮，其余逐句高亮。

注音的 `from` 和 `to` 是原始 `text` 的 UTF-16 范围，使用 `<ruby>` 和 `<rt>` 渲染。注音层不计入原文偏移。遇到跨注音边界的逐字单元，按原单元时间推进高亮，按文字范围绘制各片段。数据没有注音字段时直接显示原文。

建议资源响应头：

- 哈希歌曲文件：`Content-Type: application/json; charset=utf-8`，`Cache-Control: public, max-age=31536000, immutable`。
- `version.json`：短期缓存或重新验证，避免更新后长时间引用旧版本。
- 可使用 Brotli，但必须同时设置 `Content-Encoding: br`，浏览器才会自动解压。
- 跨域托管时配置实际站点需要的 CORS。

逐字高亮的进度：

```js
function progress(time, word) {
  if (word.end <= word.start) return time >= word.start ? 1 : 0
  return Math.max(0, Math.min(1, (time - word.start) / (word.end - word.start)))
}
```

可用文字背景渐变表现从左到右的填充。播放期间通过 `requestAnimationFrame` 读取实际音频时钟，使动画连续；暂停、跳转、切换版本时立即重新同步。不要只累加墙钟时间，也不要只依靠频率较低的 `timeupdate` 做逐字动画。

逐句滚动、点击句子跳转和译文开关可独立实现。活动行可能存在重叠，应保留同时演唱的句子。译文只有句级时间，不应套用日文逐字轴生成伪逐字翻译。

切换音频时检查剪辑。时长差异可用于排除明显不匹配的音频（例如直播版）。分唱标记只用于对应版本。

LRC 模式可在匹配原始 LRC 行后合入 `lineTimings` 的起止时间，再合入优先级更高的 `wordLines`；不要用 `lineTimings` 覆盖有逐字轴的行。

多版本接入：旧前端继续读取顶层，忽略 versions，索引无需迁移。所有演唱版本共用默认版本的时间轴（含逐字轴），任何 vocal 都按顶层时间同步高亮；`versions` 只决定显示哪些歌手。按选中 musicVocal 的 ID 查找 versions：找到时，在 `playbackTiming`、`mergeSharedCues` 等显示整理之前，把默认原始行的 `segments`／`performerIds` 换成 `singers` 中同一 row 的内容（未列出的行不显示歌手）；该项带 `text` 时改显示版本文字、`translation` 与 `romaji`，并去掉该行的注音和逐字轴；顶层 vocalId 对应默认版本，用顶层分唱；两者都不是时不显示分唱，但照常同步。`row` 指向原始播放行，不能指向返回的 `SongLyrics.lines`。时长差异仍可用于排除剪辑不同的音频（直播版等），比较时用该版本的 `duration`。修改默认行顺序或断句时，必须同步重建附加版本的 row。
