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
    cues = sorted(int(m)*60+float(s) for m,s in re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', data['lrc']) if int(m)*60+float(s)<=data['duration'])
    for row in data['lrc'].splitlines():
        text = re.sub(r'\[\d+:\d+(?:\.\d+)?\]', '', row).strip()
        if not text:
            continue
        for m, s in re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', row):
            start = int(m)*60+float(s)
            if start>data['duration']:continue
            line = {'cueStart': start, 'start': start, 'text': text}
            timing = next((w for w in data.get('lineTimings', []) if abs(w['cueStart']-start)<.001 and w['text']==text), {})
            line.update(timing)
            match = next((w for w in data.get('wordLines', []) if abs(w['cueStart']-start)<.001 and w['text']==text), {})
            line.update(match)
            result.append(line)
    result.sort(key=lambda r:r['cueStart'])
    for i, line in enumerate(result):
        line.setdefault('end', next((cue for cue in cues if cue>line['cueStart']), data['duration']))
    return result
