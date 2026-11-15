"""Read attributed lyric fragments from Sekaipedia's rendered HTML."""
import json
import re
import unicodedata
from bisect import bisect_left
from collections import Counter
from difflib import SequenceMatcher
from urllib.parse import unquote

from lxml import html

GAME_NAMES = (
    'Ichika Saki Honami Shiho Minori Haruka Airi Shizuku Kohane An Akito Toya '
    'Tsukasa Emu Nene Rui Kanade Mafuyu Ena Mizuki Miku Rin Len Luka MEIKO KAITO'
).lower().split()
SINGERS = {name: (('game_character', cid),) for cid, name in enumerate(GAME_NAMES, 1)}
SINGERS.update({
    name: tuple(('game_character', cid) for cid in members)
    for name, members in {
        'ln': range(1, 5), 'mmj': range(5, 9), 'vbs': range(9, 13),
        'wxs': range(13, 17), 'niigo': range(17, 21), '25ji': range(17, 21),
        'vs': range(21, 27),
        # https://www.sekaipedia.org/wiki/Module:LyricColor/data
        'unitleaders': (1, 5, 9, 13, 17), 'maleocs': (11, 12, 13, 16),
    }.items()
})
SINGERS.update({
    name: (('outside_character', cid),)
    for cid, names in {
        1: ('gumi',), 2: ('ia',), 3: ('flower',), 5: ('una', 'otomachi una'),
        6: ('yuki', 'kaai yuki'), 7: ('nenerobo',), 9: ('kafu',),
        10: ('gackpo', 'camui gackpo'), 11: ('sekai',), 13: ('gekiyaku',),
        16: ('zundamon',), 17: ('rei', 'adachi rei'), 18: ('rime',),
        19: ('hanakuma chifuyu',), 20: ('vy1',), 21: ('solaria',),
        22: ('akane', 'kotonoha akane'), 23: ('aoi', 'kotonoha aoi'),
        24: ('teto', 'kasane teto'), 41: ('natsuki karin',), 42: ('coko',), 43: ('haru',),
    }.items()
    for name in names
})


def name_ids(values):
    return tuple(sorted({
        identity
        for raw in values.split(',')
        if (name := raw.strip().casefold())
        for identity in SINGERS.get(name, (('unknown', name),))
    }))


def class_selector(name):
    return f"contains(concat(' ',normalize-space(@class),' '),' {name} ')"


def fragments(node, singers=()):
    if not isinstance(node.tag, str) or node.tag in ('rp', 'rt', 'sup', 'style', 'script'):
        return
    if node.tag == 'br':
        yield '\n', ()
        return
    if node.get('data-singers') is not None:
        singers = name_ids(','.join((node.get('data-singers'), node.get('data-backing', ''))))
    elif 'text-color' in node.get('class', '').split() and node.get('title') and not singers:
        singers = name_ids(node.get('title'))
    if node.text:
        yield node.text, singers
    for child in node:
        yield from fragments(child, singers)
        if child.tail:
            yield child.tail, singers


def units_for(char):
    return ''.join(c for c in unicodedata.normalize('NFKC', char).casefold()
                   if unicodedata.category(c)[0] in 'LMN')


def normalized(text):
    return ''.join(map(units_for, text))


def config_value(body, key):
    match = re.search(rf'"{key}":("(?:[^"\\]|\\.)*"|\d+)', body)
    return json.loads(match[1]) if match else None


def song_list(body):
    root = html.fromstring(body)
    paths = root.xpath(f"//table[{class_selector('wikitable')}]/tbody/tr/td[1]/a[starts-with(@href,'/wiki/')][1]/@href")
    return {unquote(path) for path in paths}, config_value(body, 'wgRevisionId')


def page_tables(body):
    root = html.fromstring(body)
    song_ids = root.xpath("//tr[th[normalize-space()='Song ID']]/td/text()")
    song_ids = [int(s.strip()) for s in song_ids if s.strip().isdecimal()]
    labels = {tab.get('id'): tab.text_content().strip() for tab in root.xpath(f"//a[{class_selector('tabber__tab')}]")}
    tables = []
    for table in root.xpath("//table[starts-with(@id,'lyrics-')]"):
        tabs = [
            labels.get(panel.get('aria-labelledby'), '?')
            for panel in reversed(list(table.iterancestors('article')))
            if 'tabber__panel' in panel.get('class', '').split()
        ]
        chars = []
        cast = set()
        cells = table.xpath(f".//td[{class_selector('lyrics-japanese')}]")
        language = 'ja' if cells else 'en'
        if not cells:
            cells = table.xpath(f".//td[{class_selector('lyrics-english')}]")
        for cell in cells:
            for text, artists in fragments(cell):
                for char in text:
                    if units := units_for(char):
                        cast.update(artists)
                        chars.append((units, artists))
        tables.append({
            'id': table.get('id'), 'tabs': tabs, 'cast': cast, 'language': language,
            'text': ''.join(part for part, _ in chars),
            'assignments': tuple(performers for part, performers in chars for _ in part),
        })
    return {
        'musicIds': song_ids,
        'title': config_value(body, 'wgTitle'),
        'revision': config_value(body, 'wgRevisionId'),
        'pageId': config_value(body, 'wgArticleId'),
        'tables': tables,
    }


def occurrences(text, part, start=0, end=None):
    end = len(text) if end is None else end
    while (pos := text.find(part, start, end)) >= 0:
        yield pos
        start = pos + 1


def align_rows(texts, table):
    """Return exact equal spans, with repeated lyrics constrained by unique neighboring rows."""
    keys = [normalized(text) for text in texts]
    local = ''.join(keys)
    source = table['text']
    if not local or not source:
        return {}, 0.0
    offsets = []
    end = 0
    for key in keys:
        offsets.append(end)
        end += len(key)
    possible = {key: tuple(occurrences(source, key)) for key in set(keys) - {''}}
    blocks = SequenceMatcher(None, local, source, autojunk=False).get_matching_blocks()
    mapped = {}
    block = 0
    for row, (key, start) in enumerate(zip(keys, offsets)):
        if not key:
            continue
        while blocks[block].a + blocks[block].size <= start and blocks[block].size:
            block += 1
        base, upstream, size = blocks[block]
        if base <= start and start + len(key) <= base + size:
            mapped[row] = upstream + start - base

    counts = Counter(keys)
    anchors = [row for row, pos in mapped.items()
               if len(keys[row]) >= 6 and counts[keys[row]] == 1 and possible[keys[row]] == (pos,)]
    source_singers = table['assignments']
    output = {}
    for row, pos in mapped.items():
        key = keys[row]
        # A surrounding unique pair establishes the occurrence even when identical choruses alternate singers.
        nearest = bisect_left(anchors, row)
        lower = (mapped[anchors[nearest - 1]] + len(keys[anchors[nearest - 1]])) if nearest else 0
        upper = mapped[anchors[nearest]] if nearest < len(anchors) and anchors[nearest] != row else len(source)
        candidates = {source_singers[p:p + len(key)] for p in possible[key]
                      if lower <= p and p + len(key) <= upper}
        if len(candidates) == 1:
            output[row] = (pos, next(iter(candidates)))
    matched_chars = sum(len(keys[row]) for row in mapped)
    return output, matched_chars / len(local)


def segments_for(text, assignments, performer_ids):
    """Put the source assignments on exact local characters; retain local spaces and punctuation."""
    offset = 0
    segments = []
    current = ()
    for char in text:
        size = len(units_for(char))
        if size:
            choices = set(assignments[offset:offset + size])
            if len(choices) != 1:
                return []
            current = next(iter(choices))
            offset += size
            if not set(current) <= performer_ids.keys():
                return []
        ids = [performer_ids[artist] for artist in current]
        if segments and segments[-1]['performerIds'] == ids:
            segments[-1]['text'] += char
        else:
            segments.append({'text': char, 'performerIds': ids})
    # Leading punctuation is grouped with its following singer.
    if segments and not segments[0]['performerIds'] and not normalized(segments[0]['text']) and len(segments) > 1:
        leading = segments.pop(0)['text']
        segments[0]['text'] = leading + segments[0]['text']
    if not any(s['performerIds'] for s in segments):
        return []
    return segments
