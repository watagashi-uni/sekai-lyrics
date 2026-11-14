"""Conservative text matching shared by offline import tools."""
import re
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def rows(data):
    if data['format'] == 'bilingual_json':
        return data['lines']
    result = []
    for row in data['lrc'].splitlines():
        text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', row).strip()
        if not text:
            continue
        for m, s in re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', row):
            start = int(m)*60+float(s)
            line = {'cueStart': start, 'start': start, 'text': text}
            match = next((w for w in data.get('wordLines', []) if abs(w['cueStart']-start)<.001 and w['text']==text), {})
            line.update(match)
            result.append(line)
    result.sort(key=lambda r:r['cueStart'])
    for i, line in enumerate(result):
        line.setdefault('end', next((r['start'] for r in result[i+1:] if r['start']>line['start']), data['duration']))
    return result
