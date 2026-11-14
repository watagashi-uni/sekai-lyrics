"""Regression checks for reviewed song readings and regeneration precedence.

Run: uv run --no-project --with Janome==0.5.0 python scripts/test-reviewed-readings.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


short = read(ROOT / 'lyrics/0131/lyrics.json')
full = read(ROOT / 'lyrics/0388/lyrics.json')
assert not full.get('wordLines') and all(not r.get('words') for r in short['lines'])
assert short['lines'][0]['start'] == 38.46
assert short['lines'][-1]['end'] == 156.46
assert short['credits']['translation'] == '雪莹ちゃん'
assert full['credits']['translation'] == '2884omgpy'
assert len(short['lines']) == 23 and len(full['lineTimings']) == 30
for s, f in zip(short['lines'], full['lineTimings'][7:]):
    assert s['text'] == f['text']
    assert abs(f['start'] - s['start'] - 139.2) < 1e-6
    assert abs(f['end'] - s['end'] - 139.2) < 1e-6
assert full['lineTimings'][1]['end'] == 66.06
assert full['lineTimings'][2]['start'] == 75.76
assert full['lineTimings'][6]['end'] == 123.86
assert full['lineTimings'][7]['start'] == 177.66

with tempfile.TemporaryDirectory(prefix='reviewed-readings-') as directory:
    fixture = Path(directory)
    (fixture / 'scripts').mkdir()
    for name in ['add-furigana.mjs', 'add-romaji.py', 'merge_common.py']:
        shutil.copy2(ROOT / 'scripts' / name, fixture / 'scripts' / name)
    expected = {}
    for mid in ['0131', '0388']:
        folder = fixture / 'lyrics' / mid
        shutil.copytree(ROOT / 'lyrics' / mid, folder)
        expected[mid] = read(folder / 'lyrics.json')
        reviewed = read(folder / 'readings.reviewed.json')['lines']
        assert len({r['text'] for r in reviewed}) == len(reviewed)
        # Simulate a stale human import which disagrees with reviewed readings.
        human_path = folder / 'romaji.sekaipedia.json'
        human = read(human_path)
        human['lines'].extend({'text': r['text'], 'romaji': 'stale source'} for r in reviewed if r.get('romaji'))
        write(human_path, human)
        data = read(folder / 'lyrics.json')
        for line in data.get('lines', data.get('rubyLines', [])):
            line['ruby'] = [{'from': 0, 'to': 1, 'reading': 'incorrect'}]
        for line in data.get('lines', data.get('romajiLines', [])):
            line['romaji'] = 'incorrect'
        write(folder / 'lyrics.json', data)
        canonical = folder / 'game.bilingual.json'
        if canonical.exists():
            data = read(canonical)
            for line in data['lines']:
                for segment in line['segments']:
                    segment['ruby'] = [{'text': segment['text'], 'reading': 'incorrect'}]
            write(canonical, data)
    for _ in range(2):
        subprocess.run(['node', str(fixture / 'scripts/add-furigana.mjs')], check=True)
        subprocess.run([sys.executable, str(fixture / 'scripts/add-romaji.py')], check=True)
        for mid, data in expected.items():
            assert read(fixture / 'lyrics' / mid / 'lyrics.json') == data, mid
print('Reviewed readings: stale imports overridden, reruns stable, both audio timelines and gaps checked.')
