"""Add romaji to the playback lyrics.

Run from the repository root (Janome is the only dependency, pinned to the version used upstream):

    uv run --no-project --with Janome==0.5.0 python scripts/add-romaji.py

Each line's reading comes from its furigana where the line has some, and from Janome's
dictionary for the rest. Particles は/へ/を are read wa/e/o, and spaces fall between words
as in Chunibot's lyric romanization, from which these rules are taken.

The romaji is added as new keys only, so players that do not know them are unaffected:
- `bilingual_json`: `romaji` on each line of `lines`;
- `lrc`: `romajiLines`, entries `{cueStart, text, romaji}` matched to the original LRC rows
  the same way as `rubyLines` (by the row's own timestamp and text, before word timing).
Lines with nothing Japanese to read (English, symbols), and lines with a kanji the dictionary
cannot read, get no romaji.
Files whose content does not change are left byte for byte as they are.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

from janome.tokenizer import Tokenizer

ROOT = Path(__file__).resolve().parents[1] / 'lyrics'

DIGRAPHS = {
    'きゃ': 'kya', 'きゅ': 'kyu', 'きょ': 'kyo', 'ぎゃ': 'gya', 'ぎゅ': 'gyu', 'ぎょ': 'gyo',
    'しゃ': 'sha', 'しゅ': 'shu', 'しょ': 'sho', 'しぇ': 'she', 'じゃ': 'ja', 'じゅ': 'ju', 'じょ': 'jo', 'じぇ': 'je',
    'ちゃ': 'cha', 'ちゅ': 'chu', 'ちょ': 'cho', 'ちぇ': 'che', 'ぢゃ': 'ja', 'ぢゅ': 'ju', 'ぢょ': 'jo',
    'にゃ': 'nya', 'にゅ': 'nyu', 'にょ': 'nyo', 'ひゃ': 'hya', 'ひゅ': 'hyu', 'ひょ': 'hyo',
    'びゃ': 'bya', 'びゅ': 'byu', 'びょ': 'byo', 'ぴゃ': 'pya', 'ぴゅ': 'pyu', 'ぴょ': 'pyo',
    'みゃ': 'mya', 'みゅ': 'myu', 'みょ': 'myo', 'りゃ': 'rya', 'りゅ': 'ryu', 'りょ': 'ryo',
    'ふぁ': 'fa', 'ふぃ': 'fi', 'ふぇ': 'fe', 'ふぉ': 'fo', 'ふゅ': 'fyu',
    'てぃ': 'ti', 'てゅ': 'tyu', 'でぃ': 'di', 'でゅ': 'dyu', 'とぅ': 'tu', 'どぅ': 'du',
    'うぃ': 'wi', 'うぇ': 'we', 'うぉ': 'wo', 'つぁ': 'tsa', 'つぃ': 'tsi', 'つぇ': 'tse', 'つぉ': 'tso',
    'くぁ': 'kwa', 'くぃ': 'kwi', 'くぇ': 'kwe', 'くぉ': 'kwo', 'ぐぁ': 'gwa', 'ぐぃ': 'gwi', 'ぐぇ': 'gwe', 'ぐぉ': 'gwo',
    'ゔぁ': 'va', 'ゔぃ': 'vi', 'ゔぇ': 've', 'ゔぉ': 'vo', 'ゔゅ': 'vyu',
}
MONOGRAPHS = {
    'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o', 'か': 'ka', 'き': 'ki', 'く': 'ku', 'け': 'ke', 'こ': 'ko',
    'が': 'ga', 'ぎ': 'gi', 'ぐ': 'gu', 'げ': 'ge', 'ご': 'go', 'さ': 'sa', 'し': 'shi', 'す': 'su', 'せ': 'se', 'そ': 'so',
    'ざ': 'za', 'じ': 'ji', 'ず': 'zu', 'ぜ': 'ze', 'ぞ': 'zo', 'た': 'ta', 'ち': 'chi', 'つ': 'tsu', 'て': 'te', 'と': 'to',
    'だ': 'da', 'ぢ': 'ji', 'づ': 'zu', 'で': 'de', 'ど': 'do', 'な': 'na', 'に': 'ni', 'ぬ': 'nu', 'ね': 'ne', 'の': 'no',
    'は': 'ha', 'ひ': 'hi', 'ふ': 'fu', 'へ': 'he', 'ほ': 'ho', 'ば': 'ba', 'び': 'bi', 'ぶ': 'bu', 'べ': 'be', 'ぼ': 'bo',
    'ぱ': 'pa', 'ぴ': 'pi', 'ぷ': 'pu', 'ぺ': 'pe', 'ぽ': 'po', 'ま': 'ma', 'み': 'mi', 'む': 'mu', 'め': 'me', 'も': 'mo',
    'や': 'ya', 'ゆ': 'yu', 'よ': 'yo', 'ら': 'ra', 'り': 'ri', 'る': 'ru', 'れ': 're', 'ろ': 'ro',
    'わ': 'wa', 'ゐ': 'wi', 'ゑ': 'we', 'を': 'o', 'ゔ': 'vu',
    'ぁ': 'a', 'ぃ': 'i', 'ぅ': 'u', 'ぇ': 'e', 'ぉ': 'o', 'ゃ': 'ya', 'ゅ': 'yu', 'ょ': 'yo', 'ゎ': 'wa',
}
PARTICLES = {'は': 'wa', 'へ': 'e', 'を': 'o'}
SPECIAL = {'こんにちは': 'konnichiwa', 'こんばんは': 'konbanwa'}
OPENING = '（([｛{「『【〈《〔［“‘"\''
CLOSING = '、。，．,.。！？!?…‥：:；;）)]｝}」』】〉》〕］”’"\''
# Japanese punctuation written the way it reads in Latin text.
PUNCTUATION = str.maketrans({
    '、': ', ', '。': '. ', '，': ', ', '．': '. ', '！': '! ', '？': '? ', '：': ': ', '；': '; ',
    '「': ' "', '」': '" ', '『': ' "', '』': '" ', '【': ' [', '】': '] ', '〈': ' <', '〉': '> ',
    '《': ' <<', '》': '>> ', '〔': ' (', '〕': ') ', '（': ' (', '）': ') ', '［': ' [', '］': '] ',
    '・': ' ', '　': ' ', '～': '~', '〜': '~', '…': '...', '‥': '..', '♪': ' ♪ ', '☆': ' ☆ ', '★': ' ★ ',
})
JAPANESE = re.compile(r'[぀-ヿ㐀-鿿豈-﫿々〆ヵヶ]')

_tokenizer: Tokenizer | None = None


def tokens(value: str) -> list:
    global _tokenizer
    _tokenizer = _tokenizer or Tokenizer()
    return list(_tokenizer.tokenize(value))


def hiragana(value: str) -> str:
    return ''.join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in value)


def syllable(text: str, index: int) -> tuple[str, int]:
    if text[index:index + 2] in DIGRAPHS:
        return DIGRAPHS[text[index:index + 2]], 2
    return MONOGRAPHS.get(text[index], text[index]), 1


def romanize_reading(value: str) -> str:
    """A kana reading in Hepburn-style romaji."""
    text = hiragana(value.strip())
    output: list[str] = []
    sokuon = False
    vowel = ''
    index = 0
    while index < len(text):
        char = text[index]
        if char == 'っ':
            sokuon = True
            index += 1
            continue
        if char == 'ー':
            if vowel:
                output.append(vowel)
            index += 1
            continue
        if char == 'ん':
            following = syllable(text, index + 1)[0] if index + 1 < len(text) else ''
            piece, used = ("n'" if following[:1].lower() in 'aiueoyn' and following else 'n'), 1
        else:
            piece, used = syllable(text, index)
        if sokuon and piece[:1].isascii() and piece[:1].isalpha():
            initial = 't' if piece.startswith('ch') else piece[0]
            if initial.lower() not in 'aiueon':
                piece = initial + piece
            sokuon = False
        output.append(piece)
        for candidate in reversed(piece.lower()):
            if candidate in 'aeiou':
                vowel = candidate
                break
        index += used
    return ''.join(output)


def pos(token) -> tuple[str, str]:
    parts = str(token.part_of_speech or '').split(',')
    return (parts[0] if parts else '', parts[1] if len(parts) > 1 else '')


def romanize_sequence(sequence: list) -> str:
    output: list[str] = []
    reading: list[str] = []

    def flush() -> None:
        if reading:
            output.append(romanize_reading(''.join(reading)))
            reading.clear()

    for token in sequence:
        surface = str(token.surface or '')
        primary, _ = pos(token)
        if surface in SPECIAL:
            flush()
            output.append(SPECIAL[surface])
        elif primary == '助詞' and surface in PARTICLES:
            flush()
            output.append(PARTICLES[surface])
        else:
            value = str(token.reading or '')
            reading.append(value if value and value != '*' else surface)
    flush()
    return ''.join(output)


def starts_block(sequence: list, index: int) -> bool:
    """Whether a new word (and so a space) begins at this token."""
    if index <= 0:
        return False
    current, previous = sequence[index], sequence[index - 1]
    surface, before = str(current.surface or ''), str(previous.surface or '')
    primary, secondary = pos(current)
    previous_primary, _ = pos(previous)
    if not surface.strip() or primary == '記号':
        return False
    if surface[0] in CLOSING or (before and before[-1] in OPENING):
        return False
    if surface == 'け' and before == 'だ':
        return False
    if primary == '助動詞':
        return surface == 'だ' and index + 1 < len(sequence) and str(sequence[index + 1].surface or '') == 'け'
    if primary == '助詞' and secondary == '接続助詞':
        return False
    if primary in ('動詞', '形容詞') and secondary == '非自立':
        return False
    if primary == '名詞' and secondary == '接尾':
        return False
    return previous_primary != '接頭詞'


def block_offsets(value: str) -> set[int]:
    found: set[int] = set()
    offset = 0
    sequence = tokens(value)
    for index, token in enumerate(sequence):
        if starts_block(sequence, index):
            found.add(offset)
        offset += len(str(token.surface or ''))
    return found


def romanize_text(value: str, *, spaced: bool = True) -> str:
    sequence = tokens(value)
    if not spaced:
        return romanize_sequence(sequence)
    blocks: list[list] = []
    for index, token in enumerate(sequence):
        if not str(token.surface or '').strip():
            continue
        if not blocks or starts_block(sequence, index):
            blocks.append([token])
        else:
            blocks[-1].append(token)
    return ' '.join(text for block in blocks if (text := romanize_sequence(block)).strip())


def romanize_line(text: str, ruby: list[dict] | None) -> str:
    """One lyric line: supplied readings where there are some, the dictionary elsewhere."""
    pieces: list[tuple[str, str]] = []
    cursor = 0
    for span in sorted(ruby or [], key=lambda r: r['from']):
        if span['from'] < cursor:
            continue
        if span['from'] > cursor:
            pieces.append((text[cursor:span['from']], ''))
        pieces.append((text[span['from']:span['to']], span['reading'].strip()))
        cursor = span['to']
    if not any(reading for _, reading in pieces):
        raw = romanize_text(text)
    else:
        if cursor < len(text):
            pieces.append((text[cursor:], ''))
        # Word boundaries come from the whole line, so a reading's text still starts a word where it should.
        boundaries = block_offsets(text)
        output: list[str] = []
        offset = 0
        for piece, reading in pieces:
            if reading:
                value = romanize_reading(reading)
            else:
                cuts = [0, *(b - offset for b in sorted(boundaries) if offset < b < offset + len(piece)), len(piece)]
                value = ' '.join(part for a, b in zip(cuts, cuts[1:]) if (part := romanize_text(piece[a:b], spaced=False)).strip())
            if output and offset in boundaries:
                output.append(' ')
            output.append(value)
            offset += len(piece)
        raw = ''.join(output)
    return tidy(raw)


KANA = re.compile(r'[\u3041-\u3096\u30a1-\u30fa\u30fcっッ]+')
IDEOGRAPH = re.compile(r'[\u3400-\u9fff\uf900-\ufaff々〆]')


def tidy(value: str) -> str:
    # Half-width kana and stray voicing marks the dictionary passed through are read as kana too.
    value = re.sub(r'[･・]{2,}', '...', value)
    value = unicodedata.normalize('NFKC', value)
    value = re.sub(r'[\u3099\u309a\u309b\u309c]', '', value)
    value = KANA.sub(lambda m: romanize_reading(m.group()), value.translate(PUNCTUATION))
    value = re.sub(r'\s+', ' ', value).strip()
    value = re.sub(r'\s+([,.!?:;)\]">])(?=\s|$)', r'\1', value)
    value = re.sub(r'([(\[<])\s+', r'\1', value)
    return value


def romaji_for(text: str, ruby: list[dict] | None) -> str | None:
    if not JAPANESE.search(text):
        return None
    value = romanize_line(text, ruby)
    # A kanji the dictionary cannot read leaves the line half done: better no romaji than that.
    return value if value and not IDEOGRAPH.search(value) and not KANA.search(value) else None


def lrc_rows(lrc: str) -> list[tuple[float, str]]:
    rows = []
    for row in lrc.splitlines():
        content = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', row).strip()
        if not content:
            continue
        for minutes, seconds in re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', row):
            rows.append((int(minutes) * 60 + float(seconds), content))
    return rows


def main() -> int:
    changed = lines = 0
    for folder in sorted(p for p in ROOT.iterdir() if p.name.isdigit()):
        path = folder / 'lyrics.json'
        original = path.read_bytes()
        data = json.loads(original)
        if data['format'] == 'bilingual_json':
            for line in data['lines']:
                value = romaji_for(line['text'], line.get('ruby'))
                if value:
                    line['romaji'] = value
                    lines += 1
                else:
                    line.pop('romaji', None)
        else:
            ruby = {(r['cueStart'], r['text']): r['ruby'] for r in data.get('rubyLines') or []}
            entries = []
            seen = set()
            for start, text in lrc_rows(data.get('lrc') or ''):
                if (start, text) in seen:
                    continue
                seen.add((start, text))
                cue = next((key for key in ruby if abs(key[0] - start) < 0.001 and key[1] == text), None)
                value = romaji_for(text, ruby.get(cue) if cue else None)
                if value:
                    entries.append({'cueStart': start, 'text': text, 'romaji': value})
                    lines += 1
            if entries:
                data['romajiLines'] = entries
            else:
                data.pop('romajiLines', None)
        output = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
        if output != original:
            path.write_bytes(output)
            changed += 1
    print(f'romaji on {lines} lines; {changed} files changed', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
