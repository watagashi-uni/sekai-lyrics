import { readFile, writeFile, readdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../lyrics/', import.meta.url))

// Match the same words even when the source uses different spaces or punctuation.
// Offsets refer to UTF-16 in the unchanged playback text.
function normalize(text) {
  let value = ''
  const offsets = []
  let offset = 0
  for (const char of text) {
    for (const normalized of char.normalize('NFKC').toLowerCase()) {
      if (/[\p{L}\p{N}]/u.test(normalized)) {
        value += normalized
        for (let i = 0; i < normalized.length; i++) offsets.push({ from: offset, to: offset + char.length })
      }
    }
    offset += char.length
  }
  return { value, offsets }
}

function sourceLine(line, segments, text) {
  if (!segments?.length || segments.map(segment => segment.text).join('') !== text) return null
  let value = ''
  const ruby = []
  for (const segment of segments) {
    const tokens = segment.ruby?.map(token => token.text).join('') === segment.text
      ? segment.ruby
      : [{ text: segment.text }]
    for (const token of tokens) {
      const from = value.length
      value += normalize(token.text).value
      if (token.reading && value.length > from) ruby.push({ from, to: value.length, reading: token.reading })
    }
  }
  return { value, ruby, start: line.start, end: line.end }
}

function joinLines(lines) {
  let value = ''
  const ruby = []
  for (const line of lines) {
    for (const span of line.ruby) ruby.push({ ...span, from: span.from + value.length, to: span.to + value.length })
    value += line.value
  }
  return { value, ruby, start: lines[0].start, end: lines.at(-1).end }
}

function uniqueIndex(text, part) {
  if (!part) return -1
  const index = text.indexOf(part)
  return index >= 0 && text.indexOf(part, index + 1) === -1 ? index : -1
}

function project(line, sources) {
  const { value, offsets } = normalize(line.text)
  if (!value) return []
  const candidates = []
  const nearby = sources.filter(source => source.start < line.end + 0.06 && source.end > line.start - 0.06)
  for (let i = 0; i < nearby.length; i++) {
    for (let n = 2; n <= 4 && i + n <= nearby.length; n++) {
      const group = nearby.slice(i, i + n)
      if (group.some((source, j) => j && source.start - group[j - 1].end > 1)) break
      candidates.push(joinLines(group))
    }
  }
  const matches = []
  for (const source of [...nearby, ...candidates]) {
    if (!source.ruby.length) continue
    const intoLine = uniqueIndex(value, source.value)
    const intoSource = uniqueIndex(source.value, value)
    if (intoLine < 0 && intoSource < 0) continue
    const shift = intoLine >= 0 ? intoLine : -intoSource
    const spans = source.ruby.flatMap(span => {
      const from = offsets[span.from + shift]?.from
      const to = offsets[span.to + shift - 1]?.to
      return from != null && to != null && to > from ? [{ from, to, reading: span.reading }] : []
    })
    matches.push({ spans, exact: source.value === value, distance: Math.abs(source.start - line.start) + Math.abs(source.end - line.end) })
  }
  const result = []
  matches.sort((a, b) => Number(b.exact) - Number(a.exact) || a.distance - b.distance)
  for (const { spans } of matches) {
    for (const span of spans) {
      if (!result.some(other => other.from < span.to && other.to > span.from)) result.push(span)
    }
  }
  return result.sort((a, b) => a.from - b.from)
}

// The upstream project also has full lyrics and other versions. Use an exact text
// match only, and leave a reading out if the project gives conflicting readings.
function projectReadings(project) {
  const byText = new Map()
  for (const rendition of project?.renditions || []) {
    for (const version of [rendition.full, rendition.game]) {
      for (const line of version?.lines || []) {
        const source = sourceLine(line, line.segments, line.japanese)
        if (!source?.ruby.length) continue
        let readings = byText.get(source.value)
        if (!readings) { readings = new Map(); byText.set(source.value, readings) }
        for (const span of source.ruby) {
          const key = `${span.from}:${span.to}`
          if (!readings.has(key)) readings.set(key, span)
          else if (readings.get(key)?.reading !== span.reading) readings.set(key, null)
        }
      }
    }
  }
  return byText
}

function exactProjectRuby(line, readings) {
  const { value, offsets } = normalize(line.text)
  return [...(readings.get(value)?.values() || [])].flatMap(span => {
    if (!span) return []
    return [{ from: offsets[span.from].from, to: offsets[span.to - 1].to, reading: span.reading }]
  })
}

function parseLrc(lrc, duration) {
  const lines = []
  for (const row of lrc.split(/\r?\n/)) {
    const text = row.replace(/\[\d+:\d+(?:\.\d+)?\]/g, '').trim()
    if (!text) continue
    for (const [, minutes, seconds] of row.matchAll(/\[(\d+):(\d+(?:\.\d+)?)\]/g)) {
      const start = Number(minutes) * 60 + Number(seconds)
      if (start <= duration) lines.push({ text, start, end: duration })
    }
  }
  lines.sort((a, b) => a.start - b.start)
  for (const [i, line] of lines.entries()) line.end = lines.slice(i + 1).find(next => next.start > line.start)?.start ?? duration
  return lines
}

const totals = { bilingual_json: 0, lrc: 0, lines: 0, readings: 0 }
for (const folder of (await readdir(root)).filter(name => /^\d+$/.test(name))) {
  const dir = path.join(root, folder)
  const source = await readFile(path.join(dir, 'game.bilingual.json'), 'utf8').catch(error => {
    if (error.code === 'ENOENT') return null
    throw error
  })
  const upstreamFile = process.argv[2] && path.join(process.argv[2], `music_${Number(folder)}.json`)
  const upstream = upstreamFile && await readFile(upstreamFile, 'utf8').catch(error => {
    if (error.code === 'ENOENT') return null
    throw error
  })
  if (!source && !upstream) continue
  const readings = projectReadings(upstream ? JSON.parse(upstream) : null)
  const sourceLines = (source ? JSON.parse(source).lines : []).filter(line => Number.isFinite(line.start) && Number.isFinite(line.end))
  const canonical = sourceLines.map(line => sourceLine(line, line.segments, line.japanese)).filter(Boolean).sort((a, b) => a.start - b.start)
  const display = sourceLines.map(line => sourceLine(line, line.display_segments ?? line.segments, line.display_text ?? line.display_japanese ?? line.japanese)).filter(Boolean).sort((a, b) => a.start - b.start)
  const file = path.join(dir, 'lyrics.json')
  const original = await readFile(file, 'utf8')
  const data = JSON.parse(original)
  let count = 0
  const lines = data.format === 'lrc' ? parseLrc(data.lrc, data.duration) : data.lines
  const rubyLines = []
  for (const line of lines) {
    const ruby = project(line, display)
    const fallback = [...project(line, canonical), ...exactProjectRuby(line, readings)]
    for (const span of fallback) {
      if (!ruby.some(other => other.from < span.to && other.to > span.from)) ruby.push(span)
    }
    ruby.sort((a, b) => a.from - b.from)
    if (!ruby.length) continue
    if (data.format === 'lrc') rubyLines.push({ cueStart: line.start, text: line.text, ruby })
    else line.ruby = ruby
    count++
    totals.readings += ruby.length
  }
  if (!count) continue
  if (rubyLines.length) data.rubyLines = rubyLines
  totals[data.format]++
  totals.lines += count
  const output = JSON.stringify(data)
  if (output !== original) await writeFile(file, output)
}
console.log(totals)
