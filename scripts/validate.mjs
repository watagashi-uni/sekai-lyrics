import { readFile, stat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import assert from 'node:assert/strict'

const root = fileURLToPath(new URL('../', import.meta.url))
const json = async p => JSON.parse(await readFile(path.join(root, p), 'utf8'))
const index = await json('playback/version.json')
const catalog = await json('catalog.json')
assert.equal(index.v, 1)
assert.equal(new Set(catalog.songs.map(s => s.musicId)).size, catalog.songs.length)
assert.equal(Object.keys(index.songs).length, catalog.songs.length)
let wordSongs = 0, wordLines = 0, wordUnits = 0
for (const song of catalog.songs) {
  const mid = song.musicId, folder = `lyrics/${String(mid).padStart(4, '0')}`
  assert.equal(song.directory, folder)
  const body = await readFile(path.join(root, folder, 'lyrics.json'))
  const hash = createHash('sha256').update(body).digest('hex').slice(0, 16)
  assert.equal(index.songs[mid], hash, `hash ${mid}`)
  assert.deepEqual(await readFile(path.join(root, 'playback', `${mid}.${hash}.json`)), body)
  const data = JSON.parse(body)
  assert.equal(data.musicId, mid)
  assert.ok(Number.isFinite(data.duration) && data.duration > 0)
  assert.ok(['lrc', 'bilingual_json'].includes(data.format))
  if (data.format === 'lrc') assert.ok(data.lrc?.includes('['))
  else assert.ok(data.lines?.length)
  let timed = 0, units = 0
  for (const line of data.format === 'lrc' ? data.wordLines || [] : data.lines) {
    assert.ok(Number.isFinite(line.start) && Number.isFinite(line.end) && line.end >= line.start)
    assert.equal(typeof line.text, 'string')
    if (data.format === 'lrc') assert.ok(Number.isFinite(line.cueStart))
    let cursor = 0
    for (const word of line.words || []) {
      assert.ok(Number.isInteger(word.from) && Number.isInteger(word.to))
      assert.ok(word.from >= cursor && word.to > word.from && word.to <= line.text.length)
      assert.ok(Number.isFinite(word.start) && Number.isFinite(word.end) && word.start >= 0 && word.end >= word.start && word.end <= data.duration + 2)
      cursor = word.to
      units++
    }
    if (line.words?.length) timed++
  }
  assert.equal(song.hasWordTiming, timed > 0)
  assert.equal(song.wordTimedLines, timed)
  assert.equal(song.wordUnits, units)
  wordSongs += timed > 0; wordLines += timed; wordUnits += units
  for (const file of ['game.lrc', 'game.zh-CN.lrc', 'game.enhanced.lrc', 'sources.json']) await stat(path.join(root, folder, file))
  const sources = await json(`${folder}/sources.json`)
  assert.equal(sources.musicId, mid)
  for (const source of sources.sources) if (source.url) assert.match(source.url, /^https?:\/\//)
}
console.log(JSON.stringify({ songs: catalog.songs.length, wordSongs, wordLines, wordUnits }, null, 2))
