"""Merge current playback coverage, archived history, and saved search batches.

ssh yokohama python3 - < scripts/collect-source-history.py > /tmp/history.json
python3 scripts/build-source-history-audit.py /tmp/history.json
"""

import collections
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'
LRC_TAG = re.compile(r'\[\d+:\d+(?:\.\d+)?\]')


def read_json(path):
    return json.loads(path.read_text())


def playback_counts(play):
    if play['format'] == 'bilingual_json':
        lines = play['lines']
        timed_rows = lines
    else:
        lines = [
            tag
            for row in play.get('lrc', '').splitlines()
            if LRC_TAG.sub('', row).strip()
            for tag in LRC_TAG.findall(row)
        ]
        timed_rows = play.get('wordLines', [])
    return (
        len(lines),
        sum(bool(row.get('words')) for row in timed_rows),
        sum(len(row.get('words', [])) for row in timed_rows),
    )


def saved_batches():
    by_song = collections.defaultdict(list)
    for path in sorted(REPORTS.glob('word-timing-search-*.json')):
        batch = read_json(path)
        for song in batch['songs']:
            by_song[song['musicId']].append({
                **song,
                'date': batch['date'],
                'evidence': str(path.relative_to(ROOT)),
            })
    return by_song


def qq_status(archived, checks):
    if not checks:
        return '有历史逐曲索引' if archived else '未找到逐曲检索记录'
    successes = sum(q['status'] in ('ok', 'empty') for q in checks)
    if not successes:
        return '本轮查询失败，待重查'
    if successes < len(checks):
        return '有成功响应及失败请求，部分关键词可重查'
    return '已完成本轮查询'


def next_step(timed, review, qq, qrc, checks, batches):
    if timed:
        return '已有逐字，可查未覆盖行'
    if review:
        return '维护者因逐字效果极差换源，保留 Typing Tube 逐句轴'
    if batches:
        if checks and all(q['status'] not in ('ok', 'empty') for q in checks):
            return '其他平台已补查，QQ 请求失败待重查'
        has_other_candidate = any(
            c.get('wordUnits')
            for batch in batches
            for p in batch['providers'].values()
            for c in p['fetched']
        )
        if has_other_candidate:
            return '本轮候选未采用，见录音版本及对齐核查结果'
        return '本轮已补查，未取得可用逐字'
    if qrc:
        return '优先复核已保存QRC候选'
    return 'QQ已查，历史快照拉取结果无歌词QRC' if qq else '未找到QQ逐曲搜索索引，待补查'


def write_csv(name, records):
    with (REPORTS / name).open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main(history_path):
    history = read_json(history_path)
    catalog = read_json(ROOT / 'catalog.json')
    batches_by_song = saved_batches()
    report = {
        'date': max(
            [history['nativeSnapshot']['created_at'][:10]]
            + [batch['date'] for batches in batches_by_song.values() for batch in batches]
        ),
        'scope': 'Current catalog, archived yokohama search evidence and saved provider search batches.',
        'limitations': [
            'Missing evidence leaves the search status unknown.',
            'QRC search results may be unrelated works, covers, incompatible recordings, or rejected candidates.',
            'NetEase YRC status refers only to the IDs explicitly checked in a saved batch.',
            'Historical word proofs describe prior mappings.',
            'Search logs without a platform label remain unlabelled.',
        ],
        'qqSnapshot': history['nativeSnapshot'],
        'songs': [],
    }
    inventory = []
    candidate_rows = []
    for song in catalog['songs']:
        music_id = song['musicId']
        mid = str(music_id)
        folder = ROOT / song['directory']
        play = read_json(folder / 'lyrics.json')
        sources = read_json(folder / 'sources.json')['sources']
        line_count, word_lines, word_units = playback_counts(play)
        timed = word_lines > 0
        assert (song['hasWordTiming'], song['wordTimedLines'], song['wordUnits']) == (
            timed, word_lines, word_units,
        ), f'Catalog word timing for {music_id} is stale'

        archived = history['qq'].get(mid)
        qq = archived or {}
        stage = history['stage'].get(mid, {})
        ne_files = history['neteaseFiles'].get(mid, [])
        batches = batches_by_song[music_id]
        reviews = [batch['maintenanceReview'] for batch in batches if 'maintenanceReview' in batch]
        qq_batches = [
            (batch['evidence'], batch['providers']['qqmusic'])
            for batch in batches if 'qqmusic' in batch['providers']
        ]
        qq_checks = [query for _, batch in qq_batches for query in batch['queries']]
        qq_success = any(q['status'] in ('ok', 'empty') for q in qq_checks)
        has_qq_index = bool(archived) or qq_success
        qq_candidates = {str(c['id']) for c in qq.get('candidates', [])}
        qq_candidates.update(str(c['id']) for q in qq_checks for c in q.get('hits', []))
        qq_pulled = {str(c['id']) for c in qq.get('fetched', [])}
        qrc = {}
        for c in qq.get('fetched', []):
            if c.get('source_format') == 'qrc' and c.get('native_unit_count') and c.get('has_lyric_content'):
                qrc[str(c['id'])] = {
                    **c,
                    'wordUnits': c['native_unit_count'],
                    'rawEvidence': 'yokohama:/data/watagashi/lyrics-alignment-trial/deliverables/qq-native-sources/' + c['words_json_path'],
                    'evidence': qq['path'],
                    'decision': 'historical_candidate',
                    'reason': '待核验同曲、录音与游戏剪辑。',
                }
        for evidence, batch in qq_batches:
            qq_pulled.update(str(c['id']) for c in batch['fetched'])
            for c in batch['fetched']:
                if c.get('format') == 'qrc' and c.get('wordUnits'):
                    qrc[str(c['id'])] = {
                        **c,
                        'rawEvidence': c.get('temporaryRawCapture', ''),
                        'evidence': evidence,
                    }

        timings = [s for s in sources if ('时间' in s['usage'] or '轴' in s['usage']) and not s['usage'].startswith('历史')]
        ne_ids = {str(s['recordId']) for s in sources if ('网易' in s['provider'] or 'netease' in s['provider'].lower()) and s.get('recordId')}
        ne_ids.update(n['recordId'] for n in ne_files)
        if str(stage.get('timingSource', '')).startswith('NetEase LRC') and stage.get('selectedId'):
            ne_ids.add(str(stage['selectedId']))
        ne_fetched = [r for batch in batches for r in batch['providers'].get('netease', {}).get('fetched', [])]
        ne_ids.update(str(r['id']) for r in ne_fetched)
        yrc_checked = {str(r['id']) for r in ne_fetched if 'yrcPayloadReturned' in r}
        yrc_found = {str(r['id']) for r in ne_fetched if r.get('format') == 'yrc'}
        history_proofs = stage.get('wordProofs', [])
        recommended = next_step(timed, reviews, has_qq_index, qrc, qq_checks, batches)
        evidence_paths = ([qq['path']] if qq.get('path') else []) + [batch['evidence'] for batch in batches]
        inventory.append({
            '歌曲ID': music_id,
            '标题': song['title'],
            '当前有逐字': timed,
            '当前逐字行': word_lines,
            '当前逐字单元': word_units,
            '当前播放行数': line_count,
            '未带逐字行数': max(0, line_count - word_lines),
            '当前时间轴来源': ' | '.join(s['provider'] + (':' + str(s['recordId']) if s.get('recordId') else '') for s in timings),
            '历史逐字匹配记录数': len(history_proofs),
            '历史逐字来源': ' | '.join(f'{s.get("provider")}:{s.get("record_id")}' for s in history_proofs),
            'QQ搜索索引': has_qq_index,
            'QQ检索状态': qq_status(archived, qq_checks),
            'QQ搜索词': json.dumps(qq.get('queries', []) + [q['query'] for q in qq_checks], ensure_ascii=False),
            'QQ候选数': len(qq_candidates) if has_qq_index else '',
            'QQ已拉取数': len(qq_pulled) if has_qq_index else '',
            'QQ已存歌词QRC数': len(qrc),
            'QQ已存歌词QRC编号': ','.join(qrc),
            '网易云已有来源或拉取编号': ','.join(sorted(ne_ids)),
            '网易云YRC核查状态': f'本轮核查 {len(yrc_checked)} 条，取得 {len(yrc_found)} 条 YRC' if yrc_checked else '未确认 YRC 核查',
            '建议下一步': recommended,
            'QQ证据路径': qq['path'] if qq.get('path') else '',
            '历史成品路径': stage.get('path', ''),
            '补查证据': ' | '.join(dict.fromkeys(evidence_paths)),
        })

        for review in reviews:
            # Older raw captures may be absent, but the maintenance decision still belongs in the ledger.
            rid = review['recordId']
            qrc[rid] = {
                'id': rid, 'title': song['title'], 'source_url': review['source_url'],
                **qrc.get(rid, {}),
                'decision': review['decision'], 'reason': review['reason'],
                'evidence': review['evidence'],
            }
        for c in qrc.values():
            candidate_rows.append({
                '歌曲ID': music_id,
                '歌曲标题': song['title'],
                '当前有逐字': timed,
                'QQ记录ID': c['id'],
                '候选标题': c.get('title'),
                '歌手': ' / '.join(c.get('artists') or []),
                '逐字单元': c.get('wordUnits', ''),
                '链接': c.get('source_url'),
                '原始逐字文件': c.get('rawEvidence', ''),
                '状态': c['decision'],
                '核验结果': c['reason'],
                '证据': c['evidence'],
            })
        report['songs'].append({
            'musicId': music_id,
            'title': song['title'],
            'hasWordTiming': timed,
            'wordTimedLines': word_lines,
            'wordUnits': word_units,
            'playbackLines': line_count,
            'currentSources': sources,
            'historicalStage': stage,
            'qqSearch': archived,
            'searchBatches': batches,
            'neteaseSourceFiles': ne_files,
            'neteaseRecordedIds': sorted(ne_ids),
            'unlabelledSearchLogs': history['unlabelledSearchLogs'].get(mid, []),
            'nextStep': recommended,
            'qqFetchedLyricQrcIds': sorted(c['id'] for c in qrc.values() if c.get('wordUnits')),
        })

    followup = [r for r in inventory if not r['当前有逐字']]
    assert len({r['歌曲ID'] for r in inventory}) == len(inventory)
    summary = {
        'songs': len(inventory),
        'withWordTiming': len(inventory) - len(followup),
        'withoutWordTiming': len(followup),
        'qqSearchIndexes': sum(r['QQ搜索索引'] for r in inventory),
        'noWordQqSearchIndexes': sum(r['QQ搜索索引'] for r in followup),
        'noWordWithFetchedQrc': sum(r['QQ已存歌词QRC数'] > 0 for r in followup),
        'noWordNoQqIndex': sum(not r['QQ搜索索引'] for r in followup),
        'noWordSearchedWithoutFetchedQrc': sum(r['QQ搜索索引'] and not r['QQ已存歌词QRC数'] for r in followup),
        'songsWithHistoricalWordProof': sum(r['历史逐字匹配记录数'] > 0 for r in inventory),
        'wordSongsWithoutHistoricalWordProof': sum(r['当前有逐字'] and not r['历史逐字匹配记录数'] for r in inventory),
        'songsWithNeteaseRecordedIds': sum(bool(r['网易云已有来源或拉取编号']) for r in inventory),
        'noWordNextSteps': dict(collections.Counter(r['建议下一步'] for r in followup)),
    }
    report['summary'] = summary
    (REPORTS / 'source-history-audit.json').write_text(
        json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n',
    )
    write_csv('source-history-audit.csv', inventory)
    write_csv('word-timing-followup.csv', sorted(followup, key=lambda r: (not r['QQ已存歌词QRC数'], r['歌曲ID'])))
    write_csv('qq-word-candidates.csv', candidate_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]))
