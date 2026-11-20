# 更新与校验

`lyrics/<四位音乐ID>/lyrics.json` 是播放资源的维护入口。LRC 和 `game.bilingual.json` 是可独立使用的成品，不会由构建脚本自动互相转换。

更新歌曲时：

1. 更新对应成品文件，保留参考版本、音频起点和来源信息。
2. 逐字单元只能使用实际保存的时间，核对 UTF-16 文字范围和发生位置；不能因为一句歌词相同，就误套另一遍副歌的时间。
3. 保留原项目分唱及来源署名，必要时同步更新 `sources.json`。作词、作曲由播放器从游戏 master 读取，歌词 `credits` 仅维护译者等来源署名。
4. LRC 歌曲的译文要逐行对应：`translationLrc` 的每一行使用所翻译原文行的时间标签，同一时间标签只有一行；一句译文跨几行原文时按原文行拆开，拆不开的整句放在第一行。`game.lrc`、`game.zh-CN.lrc` 与 `lyrics.json` 的 `lrc`、`translationLrc` 必须完全一致。
5. 更新 `catalog.json` 的统计，重新生成覆盖报告。
6. 更新罗马音：`uv run --no-project --with Janome==0.5.0 python scripts/add-romaji.py`（文字或注音改动后需要重跑；内容不变的文件不会被改写）。
7. 执行 `node scripts/build-playback.mjs` 和 `node scripts/validate.mjs`。
8. 发布：在维护服务器上用 `scripts/publish-cos.py` 增量上传（见下文）。

## 增量发布

每首歌是一个按内容哈希命名的文件，`version.json` 只是“音乐 ID → 哈希”的指针。改一首歌只会改变这一首的哈希，所以只需上传这一首的新文件，再更新 `version.json`。

`scripts/publish-cos.py` 以 COS 上当前的 `lyrics/version.json` 为基准，不需要另存“上一版索引”：

```sh
# 在维护服务器的仓库检出中，先 build-playback，再：
/data/watagashi/sekai-zh/.venv/bin/python scripts/publish-cos.py --dry-run     # 列出与线上不同的歌曲
/data/watagashi/sekai-zh/.venv/bin/python scripts/publish-cos.py               # 发布全部改动
/data/watagashi/sekai-zh/.venv/bin/python scripts/publish-cos.py --only 1,226  # 只发布这几首，其余保持线上版本
```

- 只上传哈希与线上不同、且 COS 上还没有的 `<musicId>.<hash>.json`（Brotli、`immutable`），逐个回读校验；最后写 `version.json`。
- 已发布的哈希文件不覆盖、不删除，持有旧索引的客户端仍可读取。
- 本地缺少线上已有的歌曲时默认拒绝发布，确需下架时加 `--allow-remove`。
- `--only` 写出的 `version.json` 是线上索引加指定歌曲的新哈希，与仓库中的 `playback/version.json` 不同，属预期情况。
- `version.json` 使用 `Cache-Control: no-cache`：浏览器每次用 ETag 重新验证（通常是 304）。前端最多每分钟重新验证一次索引，哈希变了才拉新文件；没变就沿用缓存。
- COS 客户端取自 `sekai_zh.publish.client()`（`$SEKAI_ZH_ROOT`，默认 `/data/watagashi/sekai-zh`），脚本本身不读取、不输出凭据。

### 推送后自动发布

yokohama 上的 `sekai-lyrics-publish.timer` 每 10 分钟用 `git ls-remote` 查看 GitHub `main`。出现新提交后，它会在独立检出 `/data/watagashi/sekai-lyrics-publisher/repo` 中依次执行 `build-playback.mjs`、`validate.mjs` 和 `publish-cos.py`，所以推送到 `main` 后最多约 10 分钟就会上线。任一步失败都不会更新 `version.json`。源文件在 `deploy/`。

- 查看日志：`journalctl -u sekai-lyrics-publish -n 50`
- 立即执行：`systemctl start sekai-lyrics-publish`
- 失败的提交记在 `failed-commit` 中，不会每次检查都重试；修复后推送新提交即可。要重跑同一个提交，删除该文件。
- 暂停自动发布：`systemctl disable --now sekai-lyrics-publish.timer`
- 自动发布会运行仓库中的构建和发布脚本，并持有 COS 写权限，所以能推送 `main` 的人等同于能发布 COS。
- 更新部署文件：把 `deploy/auto-publish.sh` 复制到 `/data/watagashi/sekai-lyrics-publisher/`，把两个 unit 复制到 `/etc/systemd/system/`，然后执行 `systemctl daemon-reload`。

`add-furigana.mjs` 默认从每首歌的 `game.bilingual.json` 提取读音。有原项目完整数据时，可传入 `music_<ID>.json` 所在目录，从相同歌词的完整版和其它演唱版本补齐读音。`lyrics.json` 中已保存的读音（曾用完整数据补齐或人工修正过）一律保留，脚本只给还没有读音的位置补读音；文字改动过的行按新文字重新提取。`--only 795,402` 只处理指定歌曲；`--rebuild` 丢弃已保存的读音、按本次输入重新推导，输入不全时会删掉读音，一般不用。内容未变的文件不改写。播放 LRC 拆分原项目歌词行时，先恢复原项目整行的读音，再按时间和匹配片段映射到各播放行。重建播放文件时直接运行 `build-playback.mjs`，它会保留 `lyrics.json` 中已经保存的注音。

歌曲当て字等复核结果写入 `readings.reviewed.json`，记录来源并按完整文字匹配；它优先于上游注音和罗马音。131／388 的替换证据、旧行分组及源视频到游戏音频的偏移见 `reports/gekishou-source-review.json`。这两版只有逐句时间，不能重新套用已停用的 QQ 逐字轴。回归检查：`uv run --no-project --with Janome==0.5.0 python scripts/test-reviewed-readings.py`，验证间奏清空、两版时间关系，以及旧来源重新导入时修正不会丢失。

只复核文字、注音而未检索逐字的批次（`reports/word-timing-search-*.json`）在歌曲项中写 `"wordTimingSearch": false`，来源清单不会把它算作逐字补查，也不改变无逐字歌曲的建议下一步。

构建脚本会按 `lyrics.json` 的原始字节计算 SHA-256，取前 16 个十六进制字符作为文件名。仅改变 JSON 排版也会改变哈希。已发布的哈希文件不覆盖。仓库的 `playback/` 只保留当前 `version.json` 引用的文件，构建时自动删除其余旧哈希文件；COS 上的旧文件不删除，供缓存着旧索引的客户端读取。

Excel 是本次快照报告，构建脚本不会自动更新它。不要在只修改了 JSON 后宣称报告也已更新。新版本应记录新的快照日期，并重新核对已收录、纯音乐和未收录歌曲的统计。

本仓库只收录可分享的文档和歌词成品；上传凭据、环境配置、音频、模型检查点和内部运行目录不应进入 Git。

## 从 Sekaipedia 补行内分唱

1. 从 [List of songs](https://www.sekaipedia.org/wiki/List_of_songs) 找歌曲页链接。用本地曲名、已存的来源链接或罗马音来源定位候选，再用歌曲页的 **Song ID** 对照 `catalog.json`。按 JP master 的 `musicVocals` 选出本地已有游戏时间轴、需要补分唱的 `vocalId`。
2. 抓取普通歌曲页的 HTML。解析器读取歌词表里的日文原词，纯英语歌词表读取英文原词。优先取 `data-singers` 和 `data-backing`，旧版取 `text-color` 的歌手名称。歌手别名和团体成员按 Sekaipedia 的定义换算成角色 ID，再用游戏 master 核对演唱类型及阵容。见 [Sekaipedia 颜色与团体定义](https://www.sekaipedia.org/wiki/Module:LyricColor/data)。
3. 先试跑并检查报告里的分页、阵容和歌词对应。匹配忽略大小写、空白和标点，保留本地显示文字。重复歌词由前后的唯一歌词约束；可能对应不同歌手的行留待复核。导入支持补上缺失标记，以及把歌手集合一致的整句标记细化为行内片段。优先保留已有行内分唱。
4. 写入后核对默认版的 `lyrics.json` 和 `game.bilingual.json`。附加版分唱写入 `versions[].singers`，沿用默认版播放行。LRC 默认版需要显示分唱时转为双语 JSON，沿用既有行的时间、译文、注音、罗马音和逐字单元。独立 LRC 继续提供原来的歌词和时间轴。

### 输入与运行

网页快照保存在临时目录。目录中需要以下文件。

| 文件 | 内容 |
| --- | --- |
| `index.html` | 原始歌曲目录 HTML，用于记录目录修订号和候选链接 |
| `targets.json` | 以歌曲 ID 字符串为键。每项包含 `title`、`directory`（如 `lyrics/0119`）、`vocalIds`（整数数组）、`candidates`（以 Wiki 页名为键的对象） |
| `pages.json` | 以候选 Wiki 页名为键。每项记录 `url`、`httpStatus`，可附 `attempts`。成功时另记录 `resolvedUrl`、`cacheKey`、`sha256`（未压缩 HTML 的哈希） |
| `html/<cacheKey>` | 成功返回的 UTF-8 HTML，使用 gzip 保存 |

从同一个 JP master `dataVersion` 读取 `musicVocals`、`gameCharacters`、`outsideCharacters`，分别保存为 master 输入目录中的 `vocals.json`、`characters.json`、`outside.json`。

```sh
capture_dir=/tmp/sekaipedia-capture
master_dir=/tmp/sekaipedia-master
master_version=7.1.0.60
batch_date=$(date +%F)

uv run --no-project --with lxml python scripts/import-sekaipedia-singers.py \
  "$capture_dir" "$master_dir" /tmp/sekaipedia-singers-preview.json \
  --master-version "$master_version"

uv run --no-project --with lxml python scripts/import-sekaipedia-singers.py \
  "$capture_dir" "$master_dir" "reports/sekaipedia-singer-search-$batch_date.json" \
  --master-version "$master_version" --date "$batch_date" --write

python3 scripts/update-catalog.py
python3 scripts/build-source-history-audit.py /tmp/source-history.json
node scripts/build-playback.mjs
node scripts/validate.mjs
node scripts/test-version-schema.mjs
```

将示例中的 `master_version` 换成实际输入的版本。试跑可用 `--ids 119 303 802` 指定歌曲。同一天的后续批次可在报告名里依次追加 `-02`、`-03` 等后缀，保留旧报告对应的来源链接。导入会在各曲 `sources.json` 记录页面修订、分页、`vocalId` 和已采用的零基播放行。重建来源清单所需的历史输入按 `scripts/build-source-history-audit.py` 开头的命令从 yokohama 收集。逐曲证据和采用结果见[首次分唱核查](../reports/sekaipedia-singer-search-2026-11-15.json)。

## 本次合并的可重跑工具

- `import-sekaipedia-romaji.py <对方只读 checkout>` 提取可精确对应的人工罗马音输入，之后运行现有 `add-romaji.py`。不读取对方译文。
- `compare-upstream-timing.py <临时工作目录>` 使用已下载的 `musicVocals.json`、`upstream/` 报告进行版本判定、顺序文字匹配与保守句尾补充。句首差超过 0.3 秒只进入待核对清单。报告中的 `line`、`upstreamLine` 均为零基下标。
- `import-vocal-versions.py <临时工作目录>` 读取精选的历史 manifest 作业、原项目歌词和 snapshot 导出。只保存合法的已对齐行，不补造缺句；重复 vocalId 只保存一份。
- `map-vocal-audio.py <临时工作目录> pilot` 先检查 15 首；检查通过门槛与阴性对照后再运行 `batch`。使用 `uv run --no-project --with numpy --with scipy python`，批量最多同时处理 4 首歌曲。下载失败可通过临时报告看到，不绕过验证。音频下载至临时目录，解码后立即删除，异常也由临时目录回收。
- `import-audio-mappings.py <临时工作目录>` 仅收录通过全曲一致性门槛且所有歌词行都在音频范围内的映射。即使波形相符也只收录逐句，不迁移逐字或多人分唱。
- 导入版本后运行 `node scripts/unify-version-singers.mjs --write`（从历史提交的逐句行重建时加 `--from <提交>`）：所有演唱版本共用默认时间轴，脚本依次按同文字顺序、同文字乱序（时间重叠）、合并拆句、同时刻相似文字，把各版本的逐句行对应到默认行，只保留分唱（`singers`），丢弃版本自带的时间与署名。相似文字只取歌手。人工结论写进 `lyrics/<id>/versions.reviewed.json`（按 vocalId）：`text` 为确实唱了不同歌词的行（可附 `translation`、`romaji`），`spread` 为版本来源简写了一段、其歌手应标到所覆盖的全部默认行，`keep` 为已确认按默认歌词处理或不采用的版本行；改后重跑。相似匹配和仍对不上的行记录在 `reports/version-singers.json` 的 `similar`、`unmatched`，`reviewed` 为空的需人工核对，清单见 `reports/version-singers-review.md`。未运行时 `validate.mjs` 会报错。
- 最后运行 `update-catalog.py`、`build-playback.mjs`、`validate.mjs`。格式回归检查为 `node scripts/test-version-schema.mjs`，音频映射的合成正负对照为 `uv run --no-project --with numpy --with scipy python scripts/test-audio-mapping.py`。

本次的合并总报告在 `reports/merge-report.json`，时间差与逐行改前／改后在 `reports/timing-comparison.json`，实际混音能量检查在 `reports/timing-audio-check.json`。混音能量只能发现某些无声区域，不能当成人声起点证据；54、731、766 的对错尚未完成独立人声级裁定。其中 731 的 57 行有 38 行共用区间，766 的 39 行有 30 行共用区间，部分大差异来自分句粒度，不能一律解释为整体时钟偏移。450 处句尾改动只采用同版本、非 review、非截零、起点接近且落在原区间内的结束时间。

Excel 仍是原快照，未重新生成。本次没有修改前端，没有推送 Git，也没有上传任何托管资源。新增字段的前端接入步骤见播放文档；未实现新字段的客户端仍可播放默认版本。

独立识别补充：`check-focus-asr.py <临时目录>` 用 faster-whisper 1.2.1 small/int8 转写三个重点音频，`audit-asr-focus.py <转写 JSON>` 只提取完整且唯一对应的原文短句作为旁证。结果见 `reports/focused-asr-audit.json`：54 没有合格对应，731 两句分别更接近不同来源的起点，766 的重复短句与两者都不一致。未将识别文本或推测词时间写入歌词，未据此解除 review。

本次附加版本合计 141 个、覆盖 108 首：A 历史对齐 88 个／71 首，B 对方逐句轴 3 个／3 首，C 单人音频映射 48 个／39 首，D 无分唱多人映射 2 个／2 首。15 首、46 个版本试点之后完成剩余 987 个版本的检查；总共核验 1,033 个音频版本，其中 9 个试点版本也由 A 覆盖。master 的 1,115 个非默认版本最终收录 141 个，其余 974 个因严格波形门槛不足或剪辑不一致跳过，详见 `reports/skipped-versions.json` 的逐项失败条件。未尝试频谱或人声分离回退，因此该数字表示本次保守收录结果，不表示其余版本无法对齐。

2026-11-14 后续复核：766 的待核对结论已由 `reports/abnormality-timing-review.json` 更新。原始网易云来源在 yokohama 找回；经游戏人声轨与独立识别核对，采用39行候选逐句轴，并修正第18行跨过间奏的句尾。前述 timing-comparison、timing-audio-check 与 focused-asr-audit 保留历史快照，不代表此次修正后的播放时间。

2026-11-14 セカイver. 分唱补充：新增 8 个来源 B 附加版本（26、93、174、198、409、574、623、742），附加版本合计 149 个、覆盖 115 首；另有 7 首改为带分唱的双语 JSON。逐行对应、时间轴核对与逐字迁移见 `reports/sekai-singers-review-2026-11-14.json`。上文 141 个／108 首为合并当时的快照。
