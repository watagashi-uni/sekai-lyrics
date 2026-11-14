# 更新与校验

`lyrics/<四位音乐ID>/lyrics.json` 是播放资源的维护入口。LRC 和 `game.bilingual.json` 是可独立使用的成品，不会由构建脚本自动互相转换。

更新歌曲时：

1. 更新对应成品文件，保留参考版本、音频起点和来源信息。
2. 逐字单元只能使用实际保存的时间，核对 UTF-16 文字范围和发生位置；不能因为一句歌词相同，就误套另一遍副歌的时间。
3. 保留原项目分唱及来源署名；必要时同步更新 `sources.json`。
4. LRC 歌曲的译文要逐行对应：`translationLrc` 的每一行使用所翻译原文行的时间标签，同一时间标签只有一行；一句译文跨几行原文时按原文行拆开，拆不开的整句放在第一行。`game.lrc`、`game.zh-CN.lrc` 与 `lyrics.json` 的 `lrc`、`translationLrc` 必须完全一致。
5. 更新 `catalog.json` 的统计，重新生成覆盖报告。
6. 更新罗马音：`uv run --no-project --with Janome==0.5.0 python scripts/add-romaji.py`（文字或注音改动后需要重跑；内容不变的文件不会被改写）。
7. 执行 `node scripts/build-playback.mjs` 和 `node scripts/validate.mjs`。
8. 发布时先上传新增哈希文件，确认可读后再更新 `version.json`。

`add-furigana.mjs` 默认从每首歌的 `game.bilingual.json` 提取读音。有原项目完整数据时，可传入 `music_<ID>.json` 所在目录，从相同歌词的完整版和其它演唱版本补齐读音。播放 LRC 拆分原项目歌词行时，先恢复原项目整行的读音，再按时间和匹配片段映射到各播放行。重建播放文件时直接运行 `build-playback.mjs`，它会保留 `lyrics.json` 中已经保存的注音。

构建脚本会按 `lyrics.json` 的原始字节计算 SHA-256，取前 16 个十六进制字符作为文件名。仅改变 JSON 排版也会改变哈希。已发布的哈希文件不覆盖；旧文件可以暂时保留，供缓存着旧索引的客户端读取。

Excel 是本次快照报告，构建脚本不会自动更新它。不要在只修改了 JSON 后宣称报告也已更新。新版本应记录新的快照日期，并重新核对已收录、纯音乐和未收录歌曲的统计。

本仓库只收录可分享的文档和歌词成品；上传凭据、环境配置、音频、模型检查点和内部运行目录不应进入 Git。

## 本次合并的可重跑工具

- `import-sekaipedia-romaji.py <对方只读 checkout>` 提取可精确对应的人工罗马音输入，之后运行现有 `add-romaji.py`。不读取对方译文。
- `compare-upstream-timing.py <临时工作目录>` 使用已下载的 `musicVocals.json`、`upstream/` 报告进行版本判定、顺序文字匹配与保守句尾补充。句首差超过 0.3 秒只进入待核对清单。报告中的 `line`、`upstreamLine` 均为零基下标。
- `import-vocal-versions.py <临时工作目录>` 读取精选的历史 manifest 作业、原项目歌词和 snapshot 导出。只保存合法的已对齐行，不补造缺句；重复 vocalId 只保存一份。
- `map-vocal-audio.py <临时工作目录> pilot` 先检查 15 首；检查通过门槛与阴性对照后再运行 `batch`。使用 `uv run --no-project --with numpy --with scipy python`，批量最多同时处理 4 首歌曲。下载失败可通过临时报告看到，不绕过验证。音频下载至临时目录，解码后立即删除，异常也由临时目录回收。
- `import-audio-mappings.py <临时工作目录>` 仅收录通过全曲一致性门槛且所有歌词行都在音频范围内的映射。即使波形相符也只收录逐句，不迁移逐字或多人分唱。
- 最后运行 `update-catalog.py`、`build-playback.mjs`、`validate.mjs`。格式回归检查为 `node scripts/test-version-schema.mjs`，音频映射的合成正负对照为 `uv run --no-project --with numpy --with scipy python scripts/test-audio-mapping.py`。

本次的合并总报告在 `reports/merge-report.json`，时间差与逐行改前／改后在 `reports/timing-comparison.json`，实际混音能量检查在 `reports/timing-audio-check.json`。混音能量只能发现某些无声区域，不能当成人声起点证据；54、731、766 的对错尚未完成独立人声级裁定。其中 731 的 57 行有 38 行共用区间，766 的 39 行有 30 行共用区间，部分大差异来自分句粒度，不能一律解释为整体时钟偏移。450 处句尾改动只采用同版本、非 review、非截零、起点接近且落在原区间内的结束时间。

Excel 仍是原快照，未重新生成。本次没有修改前端，没有推送 Git，也没有上传任何托管资源。新增字段的前端接入步骤见播放文档；未实现新字段的客户端仍可播放默认版本。

独立识别补充：`check-focus-asr.py <临时目录>` 用 faster-whisper 1.2.1 small/int8 转写三个重点音频，`audit-asr-focus.py <转写 JSON>` 只提取完整且唯一对应的原文短句作为旁证。结果见 `reports/focused-asr-audit.json`：54 没有合格对应，731 两句分别更接近不同来源的起点，766 的重复短句与两者都不一致。未将识别文本或推测词时间写入歌词，未据此解除 review。

本次附加版本合计 141 个、覆盖 108 首：A 历史对齐 88 个／71 首，B 对方逐句轴 3 个／3 首，C 单人音频映射 48 个／39 首，D 无分唱多人映射 2 个／2 首。15 首、46 个版本试点之后完成剩余 987 个版本的检查；总共核验 1,033 个音频版本，其中 9 个试点版本也由 A 覆盖。master 的 1,115 个非默认版本最终收录 141 个，其余 974 个因严格波形门槛不足或剪辑不一致跳过，详见 `reports/skipped-versions.json` 的逐项失败条件。未尝试频谱或人声分离回退，因此该数字表示本次保守收录结果，不表示其余版本无法对齐。
