// Every rendition of a song is sung to the same backing track, so all of them share the
// default rendition's timeline; they differ only in who sings which row. This turns the
// timed lines of each additional version into singer assignments on the default rows:
//
//   versions[].lines [{textRef|text, start, end, segments?, performerIds?}]
//   → versions[].singers [{row, segments?, performerIds?}]
//
// Version lines and default rows are paired in song order by text (ignoring spaces,
// punctuation and width), preferring the pairing with the least time drift. textRef only
// names *a* row with that text (the first), so repeats are told apart by order and time.
// Sentences broken differently on the two sides are joined until their texts match.
// Lines whose text the default rendition does not have are dropped and reported.
//
// Usage: node scripts/unify-version-singers.mjs [--write]
// Without --write it only prints the report. Versions already holding `singers` are left as they are.
import { readFile, writeFile, readdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defaultRows, defaultTimeline } from './version-schema.mjs'

const root = fileURLToPath(new URL('../', import.meta.url))
const write = process.argv.includes('--write')

export const normalize = text => text.normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, '')

/** Singers of each UTF-16 unit of a version line: its segments, or its line-level singers throughout. */
function lineUnits(text, line) {
  if (line.segments?.length && line.segments.map(s => s.text).join('') === text) {
    return line.segments.flatMap(s => Array.from({ length: s.text.length }, () => s.performerIds || []))
  }
  return Array.from({ length: text.length }, () => line.performerIds || [])
}

/**
 * Carry per-unit singers written for `from` onto `to`, which reads the same once normalized.
 * Characters that normalization drops (spaces, punctuation) take the singers before them.
 */
export function moveUnits(from, units, to) {
  const sung = []
  for (let i = 0; i < from.length; i++) for (let k = normalize(from[i]).length; k > 0; k--) sung.push(units[i])
  const out = []
  let cursor = 0
  let last = sung[0] || []
  for (let i = 0; i < to.length; i++) {
    const n = normalize(to[i]).length
    if (n) {
      last = sung[cursor] || last
      cursor += n
    }
    out.push(last)
  }
  return cursor === sung.length ? out : null
}

/** Units with the same singers in a row become one segment. */
function toSegments(text, units) {
  const segments = []
  for (let i = 0; i < text.length; i++) {
    const prev = segments[segments.length - 1]
    if (prev && prev.performerIds.join('\u0000') === units[i].join('\u0000')) prev.text += text[i]
    else segments.push({ text: text[i], performerIds: units[i] })
  }
  return segments
}

/** How far a default row starting at `at` lies from a version span (0 inside it). */
const driftOf = (at, line) => (at < line.start ? line.start - at : at > line.end ? at - line.end : 0)
/** Furthest a matched row may start outside the version line's span. */
const MAX_ALIGN_DRIFT_SEC = 8
/** Most rows or lines joined to match one another when the two sides break a sentence differently. */
const MAX_JOIN = 4

/**
 * Pair version lines with default rows in song order: as many equal texts as possible,
 * then the least time drift. Lines left over are tried against runs of rows (or rows
 * against runs of lines) whose joined text reads the same, for sentences broken differently.
 */
export function unifyVersion(data, version) {
  const base = defaultRows(data)
  const timeline = defaultTimeline(data)
  const D = timeline.map((row, i) => ({ i, start: row.start, text: base[i].text, key: normalize(base[i].text) }))
    .sort((a, b) => a.start - b.start || a.i - b.i)
  const V = version.lines.map((line, i) => {
    const text = line.textRef != null ? base[line.textRef]?.text : line.text
    return { i, line, text: text ?? '', key: normalize(text ?? ''), start: line.start, end: line.end }
  })
  const n = V.length
  const m = D.length
  // best[a][b]: [matches, -drift] for V[a:] against D[b:].
  const best = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(null))
  const better = (x, y) => (x[0] !== y[0] ? x[0] > y[0] : x[1] > y[1])
  for (let a = n; a >= 0; a--) {
    for (let b = m; b >= 0; b--) {
      if (a === n || b === m) { best[a][b] = [0, 0]; continue }
      let pick = best[a + 1][b]
      if (better(best[a][b + 1], pick)) pick = best[a][b + 1]
      const drift = driftOf(D[b].start, V[a])
      if (V[a].key && V[a].key === D[b].key && drift <= MAX_ALIGN_DRIFT_SEC) {
        const take = [best[a + 1][b + 1][0] + 1, best[a + 1][b + 1][1] - drift]
        if (better(take, pick)) pick = take
      }
      best[a][b] = pick
    }
  }
  const pairs = []
  for (let a = 0, b = 0; a < n && b < m;) {
    const drift = driftOf(D[b].start, V[a])
    if (V[a].key && V[a].key === D[b].key && drift <= MAX_ALIGN_DRIFT_SEC
      && best[a][b][0] === best[a + 1][b + 1][0] + 1 && best[a][b][1] === best[a + 1][b + 1][1] - drift) {
      pairs.push({ v: [a], d: [b] })
      a++
      b++
    } else if (best[a][b][0] === best[a + 1][b][0] && best[a][b][1] === best[a + 1][b][1]) a++
    else b++
  }
  // Between two matched pairs, join runs on either side where one sentence is broken differently.
  const anchors = [{ v: [-1], d: [-1] }, ...pairs, { v: [n], d: [m] }]
  const joined = []
  for (let k = 0; k + 1 < anchors.length; k++) {
    let a = anchors[k].v.at(-1) + 1
    let b = anchors[k].d.at(-1) + 1
    const aEnd = anchors[k + 1].v[0]
    const bEnd = anchors[k + 1].d[0]
    while (a < aEnd && b < bEnd) {
      let found = null
      for (let size = 3; size <= MAX_JOIN + 1 && !found; size++) {
        for (let x = 1; x < size && !found; x++) {
          const y = size - x
          if (a + x > aEnd || b + y > bEnd) continue
          const vs = V.slice(a, a + x)
          const ds = D.slice(b, b + y)
          if (vs.map(v => v.key).join('') !== ds.map(d => d.key).join('') || !vs[0].key) continue
          const span = { start: vs[0].start, end: Math.max(...vs.map(v => v.end)) }
          if (ds.some(d => driftOf(d.start, span) > MAX_ALIGN_DRIFT_SEC)) continue
          found = { v: vs.map((_, t) => a + t), d: ds.map((_, t) => b + t) }
        }
      }
      if (found) {
        joined.push(found)
        a += found.v.length
        b += found.d.length
      } else if (V[a].start <= D[b].start) a++
      else b++
    }
  }
  const singers = []
  const used = new Set()
  for (const { v, d } of [...pairs, ...joined]) {
    const lines = v.map(x => V[x])
    const rows = d.map(x => D[x])
    v.forEach(x => used.add(x))
    if (lines.length === 1 && rows.length === 1 && lines[0].text === rows[0].text) {
      const { segments, performerIds } = lines[0].line
      const entry = { row: rows[0].i }
      if (segments?.length) entry.segments = segments
      if (performerIds?.length) entry.performerIds = performerIds
      if (entry.segments || entry.performerIds) singers.push(entry)
      continue
    }
    const units = moveUnits(lines.map(l => l.text).join(''), lines.flatMap(l => lineUnits(l.text, l.line)), rows.map(r => r.text).join(''))
    if (!units) continue
    const segmented = lines.some(l => l.line.segments?.length)
    let offset = 0
    for (const row of rows) {
      const own = units.slice(offset, offset + row.text.length)
      offset += row.text.length
      if (!own.some(ids => ids.length)) continue
      const segments = toSegments(row.text, own)
      singers.push(segmented || segments.length > 1 ? { row: row.i, segments } : { row: row.i, performerIds: segments[0].performerIds })
    }
  }
  singers.sort((a, b) => a.row - b.row)
  const unmatched = V.filter(x => !used.has(x.i)).map(x => ({ text: x.text, start: x.start, end: x.end }))
  const { lines: _lines, credits: _credits, ...rest } = version
  return { version: { ...rest, singers }, unmatched, lines: n, joined: joined.length }
}

/**
 * Replace one top-level value in the JSON text, leaving every other byte as it was
 * (the files were written by Python, whose number spelling JSON.stringify does not keep).
 */
function replaceValue(body, key, value) {
  const marker = `"${key}":`
  const at = body.indexOf(marker)
  if (at < 0 || body.indexOf(marker, at + 1) >= 0) throw new Error(`${key} not found once`)
  let i = at + marker.length
  let depth = 0
  let quoted = false
  for (; i < body.length; i++) {
    const ch = body[i]
    if (quoted) {
      if (ch === '\\') i++
      else if (ch === '"') quoted = false
    } else if (ch === '"') quoted = true
    else if (ch === '[' || ch === '{') depth++
    else if (ch === ']' || ch === '}') {
      if (--depth === 0) break
    }
  }
  const out = body.slice(0, at + marker.length) + JSON.stringify(value) + body.slice(i + 1)
  JSON.parse(out)
  return out
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const report = []
  let changed = 0
  for (const folder of (await readdir(path.join(root, 'lyrics'))).sort()) {
    if (!/^\d+$/.test(folder)) continue
    const file = path.join(root, 'lyrics', folder, 'lyrics.json')
    const body = await readFile(file, 'utf8')
    const data = JSON.parse(body)
    if (!data.versions?.some(v => v.lines)) continue
    data.versions = data.versions.map((version) => {
      if (!version.lines) return version
      const result = unifyVersion(data, version)
      report.push({ musicId: data.musicId, vocalId: version.vocalId, lines: result.lines, singers: result.version.singers.length, joined: result.joined, unmatched: result.unmatched })
      return result.version
    })
    if (write) {
      await writeFile(file, replaceValue(body, 'versions', data.versions))
      changed++
    }
  }
  const unmatched = report.flatMap(r => r.unmatched.map(u => ({ musicId: r.musicId, vocalId: r.vocalId, ...u })))
  console.log(JSON.stringify({ versions: report.length, lines: report.reduce((n, r) => n + r.lines, 0), unmatched: unmatched.length, files: changed }))
  for (const u of unmatched) console.log(JSON.stringify(u))
  if (write) await writeFile(path.join(root, 'reports', 'version-singers.json'), JSON.stringify({ note: 'Additional versions share the default timeline; their timed lines were turned into singer assignments on default rows by normalized text and nearest time after removing each version\'s median offset.', maxDriftSec: MAX_ALIGN_DRIFT_SEC, versions: report }, null, 1) + '\n')
}
