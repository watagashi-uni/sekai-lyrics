import { readFile, stat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import assert from 'node:assert/strict'

const root = fileURLToPath(new URL('../', import.meta.url))
const json = async p => JSON.parse(await readFile(path.join(root, p), 'utf8'))
/** Timestamps of the LRC rows that carry text. */
const timedStamps = text => (text || '').split(/\r?\n/).flatMap((row) => {
  const stamps = [...row.matchAll(/\[\d+:\d+(?:\.\d+)?\]/g)].map(match => match[0])
  return row.replace(/\[\d+:\d+(?:\.\d+)?\]/g, '').trim() ? stamps : []
})
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
  if (data.format === 'lrc') {
    assert.ok(data.lrc?.includes('['))
    // The standalone LRC files carry the same text as the playback fields.
    assert.equal(await readFile(path.join(root, folder, 'game.lrc'), 'utf8'), data.lrc, `game.lrc ${mid}`)
    assert.equal(await readFile(path.join(root, folder, 'game.zh-CN.lrc'), 'utf8'), data.translationLrc ?? '', `game.zh-CN.lrc ${mid}`)
    // Each translation row sits on the timestamp of the lyric line it translates, one row per line,
    // so a player never has to stretch one translation over the lines that follow it.
    const lyricStamps = new Set(timedStamps(data.lrc)), translationStamps = timedStamps(data.translationLrc)
    for (const stamp of translationStamps) assert.ok(lyricStamps.has(stamp), `translation row ${stamp} of ${mid} is not on a lyric line`)
    assert.equal(new Set(translationStamps).size, translationStamps.length, `two translation rows share a timestamp in ${mid}`)
  } else assert.ok(data.lines?.length)
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
  const rubyLines = data.format === 'lrc' ? data.rubyLines || [] : data.lines
  for (const line of rubyLines) {
    if (data.format === 'lrc') assert.ok(Number.isFinite(line.cueStart) && line.cueStart >= 0 && line.cueStart <= data.duration)
    let cursor = 0
    for (const span of line.ruby || []) {
      assert.ok(Number.isInteger(span.from) && Number.isInteger(span.to))
      assert.ok(span.from >= cursor && span.to > span.from && span.to <= line.text.length)
      assert.ok(typeof span.reading === 'string' && span.reading.trim())
      cursor = span.to
    }
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
