"""Overlay documented Sekaipedia singers onto the repository's existing playback rows.

uv run --no-project --with lxml python scripts/import-sekaipedia-singers.py CAPTURE MASTER REPORT --master-version VERSION [--write]
CAPTURE contains index.html, targets.json (musicId to title, directory, vocalIds and candidate page
titles), pages.json (title to request receipt and cacheKey), and html/<cacheKey> (gzip).
MASTER contains vocals.json, characters.json and outside.json from the same JP snapshot.
Without --write, REPORT describes the proposed updates and the song files are read-only.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlencode, urlsplit

from merge_common import rows
from sekaipedia_singers import align_rows, normalized, page_tables, segments_for, song_list

ROOT = Path(__file__).resolve().parents[1]
STAMP = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')
LICENSE = 'CC BY-SA 4.0'
LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/4.0/'
METHOD = '以 JP master 的演唱类型和阵容筛选分页，按游戏歌词顺序精确匹配正文。重复文字以相邻的唯一歌词和候选分唱一致性消歧。忽略大小写、空白与标点。'
RIN_GUEST = 'Wiki 原曲另标客串的镜音铃。此处只采用完全属于游戏 master 阵容（初音ミク、巡音ルカ）的行。'
INDEX_URL = 'https://www.sekaipedia.org/wiki/List_of_songs'


def load(path):
    return json.loads(path.read_bytes())


def save(path, data, indent=2):
    separators = None if indent else (',', ':')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent, separators=separators) + ('\n' if indent else ''))


def cast(vocal):
    return {(p['characterType'], p['characterId']) for p in vocal['characters']}


def performer_identity(performer, outside_by_name):
    if performer.get('characterId') is not None:
        return 'game_character', performer['characterId']
    if match := re.fullmatch(r"歌唱者-(\d+)", str(performer['performerId'])):
        return 'game_character', int(match[1])
    if cid := performer.get('outsideCharacterId') or outside_by_name.get(performer['name']):
        return 'outside_character', cid
    return None


def singer_groups(row, full_text):
    segments = row.get('segments', [])
    if not segments or ''.join(s['text'] for s in segments) != full_text:
        return set()
    return {tuple(sorted(s.get('performerIds', []))) for s in segments if normalized(s['text'])}


def proposed(row, segments, text):
    existing = singer_groups(row, text)
    names = set(row.get('performerIds', []))
    names.update(pid for group in existing for pid in group)
    names.update(pid for segment in row.get('segments', []) for pid in segment.get('performerIds', []))
    incoming = {pid for segment in segments for pid in segment['performerIds']}
    if len(existing) > 1 or not incoming:
        return None
    if not names:
        return 'missing'
    if names == incoming and len(singer_groups({'segments': segments}, text) - {()}) > 1:
        return 'split'
    return None


def tab_kind(table):
    labels = ' / '.join(table['tabs']).casefold().replace('virutal', 'virtual')
    if any(word in labels for word in ('archive', 'live', 'ensemble', 'alt. group', 'movie', '?')):
        return 'other'
    if 'april fool' in labels:
        return 'april_fool_2022' if "' 2022" in labels else 'other'
    if 'alternate vocal' in labels or 'another vocal' in labels:
        return 'another_vocal'
    if 'virtual singer' in labels or 'vocaloid' in labels:
        return 'virtual'
    if any(x == 'sekai' or x.startswith('sekai ver') for x in (s.casefold() for s in table['tabs'])):
        return 'sekai'
    return None


def vocal_kind(vocal):
    kind = vocal['musicVocalType']
    if 'colorful live' in vocal['caption'].casefold():
        return 'other'
    return 'virtual' if kind in ('original_song', 'virtual_singer') else kind


def evaluate(table, vocal, other_vocals, texts):
    if not table['text']:
        return None, 'no_lyric_text'
    if not table['cast']:
        return None, 'no_singer_tags'
    wanted = cast(vocal)
    category = tab_kind(table)
    vocal_type = vocal_kind(vocal)
    labels = [s.casefold() for s in table['tabs']]
    size_rank = 2 if any(s in ('game version', 'game size') for s in labels) else 1
    if any('full' in s for s in labels):
        size_rank = 0
    exact_cast = table['cast'] == wanted
    # Rin is a guest in the original recording of Rin-chan Now!. Game master lists
    # only Miku and Luka. Only import spans whose vocalists are all in that master cast.
    guest_known = vocal['id'] == 761 and table['cast'] == wanted | {('game_character', 22)}
    if not (exact_cast or guest_known):
        return None, 'cast_mismatch'
    if category and category != vocal_type:
        return None, 'version_type_mismatch'
    if not category and vocal_type not in ('virtual', 'sekai'):
        return None, 'unlabelled_version'
    if sum(cast(v) == wanted and (category is None or vocal_kind(v) == category) for v in other_vocals) != 1:
        return None, 'nonunique_cast'
    matches, coverage = align_rows(texts, table)
    if coverage < 0.5:
        return None, 'insufficient_ordered_text'
    return ((exact_cast, size_rank, bool(category), coverage), matches), None


def playback_rows(data):
    if data['format'] == 'bilingual_json':
        return data['lines']
    play_rows = rows(data)
    translations = {}
    for row in data.get('translationLrc', '').splitlines():
        text = STAMP.sub('', row).strip()
        for minute, sec in STAMP.findall(row):
            translations[int(minute) * 60 + float(sec)] = text
    annotations = {
        key: {(r['cueStart'], r['text']): r for r in data.get(key, [])}
        for key in ('rubyLines', 'romajiLines')
    }
    for row in play_rows:
        pair = (row.pop('cueStart'), row['text'])
        if translation := translations.get(pair[0]):
            row['translation'] = translation
        if ruby := annotations['rubyLines'].get(pair):
            row['ruby'] = ruby['ruby']
        if romaji := annotations['romajiLines'].get(pair):
            row['romaji'] = romaji['romaji']
            row['romajiSource'] = romaji['source']
        assert 0 <= row['start'] <= row['end'] <= data['duration'] + .00001
    assert sum(len(r.get('words', [])) for r in play_rows) == sum(len(r['words']) for r in data.get('wordLines', []))
    return play_rows


def bilingual_overlay(data, selected, performer_ids, performers):
    source_lines = data['lines']
    texts = [r.get('display_text', r.get('display_japanese', r['japanese'])) for r in source_lines]
    mapping, _ = align_rows(texts, selected)
    for index, (_, identities) in mapping.items():
        line = source_lines[index]
        text = texts[index]
        segments = segments_for(text, identities, performer_ids)
        existing = {
            'segments': line.get('display_segments', line.get('segments', [])),
            'performerIds': line.get('trailingPerformerIds', []),
        }
        if proposed(existing, segments, text):
            # Keep the original segments and nested ruby available to reading imports.
            key = 'segments' if text == line['japanese'] and not line.get('segments') and 'display_segments' not in line else 'display_segments'
            line[key] = segments
    data['performers'] = list({p['performerId']: p for p in data.get('performers', []) + performers}.values())


def update_vocal(folder, play, current_rows, selected, matches, vocal, alternate, names, outside, updates):
    default = alternate is None
    old_performers = play.get('performers', []) if default else alternate['performers']
    performers = list(old_performers)
    outside_by_name = {name: cid for cid, name in outside.items()}
    identities = {performer_identity(p, outside_by_name): p for p in performers}
    for kind, cid in sorted(cast(vocal)):
        if (kind, cid) in identities:
            continue
        if kind == 'game_character':
            performer = {'performerId': f'歌唱者-{cid:02}', 'name': names[cid], 'characterId': cid}
        else:
            performer = {'performerId': f'外部歌唱者-{cid}', 'name': outside[cid],
                         'characterId': None, 'outsideCharacterId': cid}
        identities[kind, cid] = performer
        performers.append(performer)
    performer_ids = {key: p['performerId'] for key, p in identities.items() if key in cast(vocal)}
    old_singers = {} if default else {r['row']: r for r in alternate['singers']}
    changes = []
    for index, (source_pos, assignments) in matches.items():
        row = current_rows[index] if default else old_singers.get(index, {})
        text = row.get('text', current_rows[index]['text'])
        segments = segments_for(text, assignments, performer_ids)
        if change := proposed(row, segments, text):
            split = len(singer_groups({'segments': segments}, text) - {()}) > 1
            changes.append({'row': index, 'sourceNormalizedOffset': source_pos, 'change': change, 'withinLine': split,
                            'performerIds': [s['performerIds'] for s in segments]})
            if updates is not None:
                if default:
                    row['segments'] = segments
                    row.pop('performerIds', None)
                else:
                    entry = old_singers.setdefault(index, {'row': index})
                    entry['segments'] = segments
                    entry.pop('performerIds', None)
    if not changes or updates is None:
        return changes
    if default:
        play['performers'] = performers
        if play['format'] == 'lrc':
            for key in ('lrc', 'translationLrc', 'lineTimings', 'wordLines', 'rubyLines', 'romajiLines'):
                play.pop(key, None)
            play['format'] = 'bilingual_json'
            play['lines'] = current_rows
        bilingual_path = folder / 'game.bilingual.json'
        if bilingual_path.exists():
            bilingual = load(bilingual_path)
            bilingual_overlay(bilingual, selected, performer_ids, performers)
        else:
            bilingual = {'music_id': play['musicId'], 'time_origin': 'selected_game_recording_start_including_pre_roll',
                         'performers': performers, 'lines': [{
                             'index': None, 'start': r['start'], 'end': r['end'],
                             'japanese': r['text'], 'zh-CN': r.get('translation', ''),
                             'segments': r.get('segments', []),
                         } for r in current_rows]}
        updates.append((bilingual_path, bilingual, 2))
    else:
        alternate['performers'] = performers
        alternate['singers'] = [entry for _, entry in sorted(old_singers.items())]
    return changes


def main(args):
    if args.write and args.report.exists():
        raise SystemExit(f'An existing evidence report must be retained: {args.report}')
    results = []
    updates = [] if args.write else None
    targets = load(args.capture / 'targets.json')
    receipts = load(args.capture / 'pages.json')
    index_bytes = (args.capture / 'index.html').read_bytes()
    index_paths, index_revision = song_list(index_bytes.decode())
    catalog = load(ROOT / 'catalog.json')
    known = {s['musicId']: s for s in catalog['songs']}
    names = {r['id']: r.get('firstName', '') + r['givenName'] for r in load(args.master / 'characters.json')}
    outside = {r['id']: r['name'] for r in load(args.master / 'outside.json')}
    songs_vocals = defaultdict(list)
    for vocal in load(args.master / 'vocals.json'):
        songs_vocals[vocal['musicId']].append(vocal)
    totals = Counter()
    for key, target in targets.items():
        mid = int(key)
        if args.ids and mid not in args.ids:
            continue
        folder = ROOT / target['directory']
        play = load(folder / 'lyrics.json')
        provider = {'queries': [], 'fetched': []}
        tables = []
        for title in target['candidates']:
            if title not in receipts:
                continue
            receipt = receipts[title]
            status = receipt['httpStatus']
            query = {'query': title, 'url': receipt['url'], 'httpStatus': status,
                     'listedInSongList': unquote(urlsplit(receipt['url']).path) in index_paths,
                     'status': 'ok' if status == 200 else ('empty' if status == 404 else 'error')}
            provider['queries'].append(query)
            if status != 200:
                if receipt.get('attempts'):
                    query['attempts'] = receipt['attempts']
                continue
            body = gzip.decompress((args.capture / 'html' / receipt['cacheKey']).read_bytes()).decode()
            page = page_tables(body)
            url = receipt['resolvedUrl']
            page_id = page['pageId']
            revision = page['revision']
            rev_url = f"{url}?{urlencode({'oldid': revision})}"
            candidate = {
                'id': f'{page_id}@{revision}', 'source_url': rev_url,
                'title': page['title'], 'format': 'MediaWiki HTML', 'wordUnits': 0,
                'songIds': page['musicIds'], 'revision': revision, 'sha256': receipt['sha256'],
                'tables': [{
                    'id': t['id'], 'tabs': t['tabs'],
                    'artists': [names.get(cid, str(cid)) if kind == 'game_character'
                                else outside.get(cid, str(cid)) if kind == 'outside_character'
                                else str(cid) for kind, cid in sorted(t['cast'])],
                    'lyricUnits': len(t['text']), 'language': t['language'],
                } for t in page['tables']],
            }
            provider['fetched'].append(candidate)
            if mid in page['musicIds'] and revision:
                tables.extend((candidate, t) for t in page['tables'])
        versions = {v['vocalId']: v for v in play.get('versions', [])}
        vocals = songs_vocals[mid]
        base = next(v for v in vocals if v['id'] == play.get('vocalId') or v['assetbundleName'] == play.get('assetbundle'))
        current_rows = playback_rows(play)
        decisions = []
        adopted = []
        for vocal in vocals:
            vid = vocal['id']
            if vid not in target['vocalIds']:
                continue
            default = vid == base['id']
            alternate = None if default else versions[vid]
            own_texts = {r['row']: r['text'] for r in alternate['singers'] if 'text' in r} if alternate else {}
            texts = [own_texts.get(i, r['text']) for i, r in enumerate(current_rows)]
            choices = []
            checks = []
            for candidate, table in tables:
                evaluation, blocked = evaluate(table, vocal, vocals, texts)
                if evaluation:
                    rank, matches = evaluation
                    choices.append((rank, matches, candidate, table))
                checks.append({'id': candidate['id'], 'table': table['id'],
                               'status': blocked or 'compatible',
                               **({'matchedTextFraction': round(evaluation[0][-1], 4)} if evaluation else {})})
            decision = {'vocalId': vid, 'default': default, 'assetbundle': vocal['assetbundleName'], 'checks': checks}
            decisions.append(decision)
            if not choices:
                decision['status'] = 'no_matching_table'
                continue
            best = max(choices, key=lambda item: item[0])
            if any(other[0] == best[0] and other[1] != best[1] for other in choices):
                decision['status'] = 'ambiguous_tables'
                continue
            rank, matches, candidate, table = best
            changes = update_vocal(folder, play, current_rows, table, matches, vocal, alternate, names, outside, updates)
            decision.update({'recordId': candidate['id'], 'source_url': candidate['source_url'],
                             'table': table['id'], 'tabs': table['tabs'], 'alignedRows': len(matches),
                             'playbackRows': len(texts), 'matchedTextFraction': round(rank[-1], 4),
                             'status': ('adopted' if args.write else 'proposed') if changes else 'no_missing_compatible_assignments',
                             'rows': changes})
            if not rank[0]:
                decision['castNote'] = RIN_GUEST
            if changes:
                adopted.append(decision)
                totals['defaultVersions' if default else 'alternateVersions'] += 1
                totals['withinLineRows'] += sum(row['withinLine'] for row in changes)
                totals.update(r['change'] for r in changes)
        if adopted:
            totals['songsChanged'] += 1
        if args.write and adopted:
            provenance_path = folder / 'sources.json'
            provenance = load(provenance_path)
            for decision in adopted:
                ref = {
                    'usage': '歌词分唱', 'provider': 'Sekaipedia', 'recordId': decision['recordId'],
                    'url': decision['source_url'], 'license': LICENSE, 'licenseUrl': LICENSE_URL,
                    'vocalId': decision['vocalId'], 'table': decision['table'], 'tabs': decision['tabs'],
                    'evidence': str(args.report.resolve().relative_to(ROOT)),
                    'playbackRows': [r['row'] for r in decision['rows']],
                    'note': METHOD + decision.get('castNote', ''),
                }
                provenance['sources'].append(ref)
                credit = [ref['url'], LICENSE, LICENSE_URL]
                if credit not in play['sources']:
                    play['sources'].append(credit)
            updates.extend(((provenance_path, provenance, 2), (folder / 'lyrics.json', play, None)))
            known[mid].update({'format': play['format'], 'sources': play['sources'],
                               'performerTagged': play['format'] == 'bilingual_json' and any(
                                   r.get('performerIds') or any(s.get('performerIds') for s in r.get('segments', []))
                                   for r in play['lines'])})
        status = ('已补分唱' if args.write else '匹配到可补分唱') if adopted else (
            '未拉到页面' if not provider['fetched'] else
            '无匹配的带分唱版本' if not any(d.get('recordId') for d in decisions) else '无可补的分唱片段')
        results.append({
            'musicId': mid, 'title': target['title'], 'providers': {'sekaipedia': provider},
            'singerReview': {'status': status, 'versions': decisions},
        })
    report = {
        'date': args.date,
        'selection': '核查已收录的多人演唱版本，包括默认与附加版本。',
        'method': METHOD,
        'masterVersion': args.master_version,
        'songList': {
            'url': INDEX_URL, 'revision': index_revision, 'httpStatus': 200, 'links': len(index_paths),
            'sha256': sha256(index_bytes).hexdigest(),
        },
        'summary': {'songsChecked': len(results), **totals},
        'songs': results,
    }
    # Keep one observation per line so subsequent searches are easy to diff.
    header = json.dumps({k: v for k, v in report.items() if k != 'songs'}, ensure_ascii=False, indent=2)
    observations = ',\n'.join('    ' + json.dumps(song, ensure_ascii=False) for song in results)
    args.report.write_text(header[:-2] + ',\n  "songs": [\n' + observations + '\n  ]\n}\n')
    if updates is not None:
        for path, value, indent in updates:
            save(path, value, indent)
        save(ROOT / 'catalog.json', catalog)
    print(json.dumps(report['summary'], ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('master', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--master-version', required=True, help='JP master dataVersion of the supplied files')
    parser.add_argument('--date', default=date.today().isoformat())
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--ids', type=int, nargs='+')
    main(parser.parse_args())
