// Every rendition of a song is sung to the same backing track, so all of them share the
// default rendition's timeline; they differ in who sings which row and, on a few rows, in
// the words. This turns the timed lines of each additional version into singer
// assignments on the default rows:
//
//   versions[].lines [{textRef|text, start, end, segments?, performerIds?}]
//   → versions[].singers [{row, segments?, performerIds?, text?, translation?, romaji?}]
//
// Version lines are paired with default rows in four passes, each only between lines whose
// times meet (textRef only names the first row with a text, so it never decides alone):
//   1. same text, in song order, least time drift;
//   2. same text, out of order (rows sung over each other, or rows of one cue that all
//      carry the cue's start);
//   3. runs of lines and rows whose joined texts are the same (sentences broken differently);
//   4. lines a person marked `spread` (a stretch the version source wrote shorter): their
//      singers go to every default row they cover;
//   5. similar text at the same time. Only the singers are taken, unless the version's
//      words were reviewed as really sung differently (`text`): then the row shows them,
//      with the reviewed translation and romaji.
// Reviews live in lyrics/<id>/versions.reviewed.json, per vocal id: `text` [{text,
// translation?, romaji?}], `spread` [version text], `keep` [version text shown with the
// default words / left out on purpose]. What is not reviewed is reported
// (reports/version-singers.json) for a person to check.
//
// Usage: node scripts/unify-version-singers.mjs [--write] [--from <git revision>]
// Without --write it only prints the report. Versions already holding `singers` are left as
// they are, unless --from names a revision whose timed lines they are rebuilt from.
import { readFile, writeFile, readdir } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
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
/** Furthest a matched row may start outside the version line's span (pass 1 and 3). */
const MAX_ALIGN_DRIFT_SEC = 8
/** Most rows or lines joined to match one another when the two sides break a sentence differently. */
const MAX_JOIN = 4
/** Least similarity of two texts sung at the same time to take one's singers for the other. */
const MIN_SIMILARITY = 0.5

/** The spans overlap, or the row starts within `tolerance` of the line. */
const meet = (v, d, tolerance) => Math.min(v.end, d.end) > Math.max(v.start, d.start) || driftOf(d.start, v) <= tolerance

/** Dice coefficient of character bigrams of two normalized texts. */
export function similarity(a, b) {
  if (!a || !b) return 0
  if (a === b) return 1
  const grams = text => (text.length < 2 ? [text] : Array.from({ length: text.length - 1 }, (_, i) => text.slice(i, i + 2)))
  const left = grams(a)
  const right = new Map()
  for (const g of grams(b)) right.set(g, (right.get(g) || 0) + 1)
  let shared = 0
  for (const g of left) if (right.get(g)) { shared++; right.set(g, right.get(g) - 1) }
  return (2 * shared) / (left.length + grams(b).length)
}

const unionOf = line => [...new Set([...(line.segments || []).flatMap(s => s.performerIds || []), ...(line.performerIds || [])])]

/** One vocal's review: version words to show, lines to spread, lines settled as they are. */
export function reviewOf(entry = {}) {
  return {
    text: new Map((entry.text || []).map(item => (typeof item === 'string' ? [item, {}] : [item.text, item]))),
    spread: new Set(entry.spread || []),
    keep: new Set(entry.keep || []),
  }
}

/** Pair version lines with default rows (see the passes above), following `review`. */
export function unifyVersion(data, version, review = reviewOf()) {
  const base = defaultRows(data)
  const timeline = defaultTimeline(data)
  const D = timeline.map((row, i) => ({ i, start: row.start, end: row.end, text: base[i].text, key: normalize(base[i].text) }))
    .sort((a, b) => a.start - b.start || a.i - b.i)
  const V = version.lines.map((line, i) => {
    const text = line.textRef != null ? base[line.textRef]?.text : line.text
    // A line to spread keeps out of the text passes (its empty key matches nothing there).
    return { i, line, text: text ?? '', key: review.spread.has(text) ? '' : normalize(text ?? ''), start: line.start, end: line.end }
  })
  const n = V.length
  const m = D.length
  const usedV = new Set()
  const usedD = new Set()
  const matches = []
  const take = (kind, v, d) => {
    v.forEach(x => usedV.add(x))
    d.forEach(x => usedD.add(x))
    matches.push({ kind, v, d })
  }
  // 1. In order. best[a][b]: [matches, -drift] for V[a:] against D[b:].
  const best = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(null))
  const better = (x, y) => (x[0] !== y[0] ? x[0] > y[0] : x[1] > y[1])
  for (let a = n; a >= 0; a--) {
    for (let b = m; b >= 0; b--) {
      if (a === n || b === m) { best[a][b] = [0, 0]; continue }
      let pick = best[a + 1][b]
      if (better(best[a][b + 1], pick)) pick = best[a][b + 1]
      const drift = driftOf(D[b].start, V[a])
      if (V[a].key && V[a].key === D[b].key && drift <= MAX_ALIGN_DRIFT_SEC) {
        const next = [best[a + 1][b + 1][0] + 1, best[a + 1][b + 1][1] - drift]
        if (better(next, pick)) pick = next
      }
      best[a][b] = pick
    }
  }
  for (let a = 0, b = 0; a < n && b < m;) {
    const drift = driftOf(D[b].start, V[a])
    if (V[a].key && V[a].key === D[b].key && drift <= MAX_ALIGN_DRIFT_SEC
      && best[a][b][0] === best[a + 1][b + 1][0] + 1 && best[a][b][1] === best[a + 1][b + 1][1] - drift) {
      take('exact', [a], [b])
      a++
      b++
    } else if (best[a][b][0] === best[a + 1][b][0] && best[a][b][1] === best[a + 1][b][1]) a++
    else b++
  }
  // 2. Out of order, where the times meet.
  for (let a = 0; a < n; a++) {
    if (usedV.has(a) || !V[a].key) continue
    const pick = D.map((d, b) => ({ d, b }))
      .filter(({ d, b }) => !usedD.has(b) && d.key === V[a].key && meet(V[a], d, 3))
      .sort((x, y) => Math.abs(x.d.start - V[a].start) - Math.abs(y.d.start - V[a].start))[0]
    if (pick) take('reordered', [a], [pick.b])
  }
  // 3. Runs of free lines against runs of free rows that read the same joined.
  for (let a = 0; a < n; a++) {
    if (usedV.has(a) || !V[a].key) continue
    let found = null
    for (let size = 3; size <= MAX_JOIN + 1 && !found; size++) {
      for (let x = 1; x < size && !found; x++) {
        const y = size - x
        const vs = Array.from({ length: x }, (_, t) => a + t)
        if (vs.some(t => t >= n || usedV.has(t) || !V[t].key)) continue
        const key = vs.map(t => V[t].key).join('')
        const span = { start: V[a].start, end: Math.max(...vs.map(t => V[t].end)) }
        for (let b = 0; b + y <= m && !found; b++) {
          const ds = Array.from({ length: y }, (_, t) => b + t)
          if (ds.some(t => usedD.has(t)) || ds.some(t => driftOf(D[t].start, span) > MAX_ALIGN_DRIFT_SEC)) continue
          if (ds.map(t => D[t].key).join('') === key) found = [vs, ds]
        }
      }
    }
    if (found) take('joined', ...found)
  }
  // 4. Reviewed stretches: every free row the line covers takes its singers.
  const overlap = (v, d) => Math.max(0, Math.min(v.end, d.end) - Math.max(v.start, d.start))
  const spreading = V.filter(v => !usedV.has(v.i) && review.spread.has(v.text))
  const spreadRows = new Map()
  for (let b = 0; b < m; b++) {
    if (usedD.has(b)) continue
    const owner = spreading.map(v => ({ v, share: overlap(v, D[b]) })).filter(x => x.share > 0).sort((x, y) => y.share - x.share)[0]
    if (owner) spreadRows.set(owner.v.i, [...(spreadRows.get(owner.v.i) || []), b])
  }
  for (const [a, rows] of spreadRows) take('spread', [a], rows)
  // 5. Similar text at the same time.
  const similar = []
  for (let a = 0; a < n; a++) {
    if (usedV.has(a)) continue
    for (let b = 0; b < m; b++) {
      if (usedD.has(b) || !meet(V[a], D[b], 2)) continue
      const score = similarity(V[a].key, D[b].key)
      if (score >= MIN_SIMILARITY) similar.push({ a, b, score })
    }
  }
  for (const { a, b } of similar.sort((x, y) => y.score - x.score)) {
    if (usedV.has(a) || usedD.has(b)) continue
    take('similar', [a], [b])
  }

  const singers = []
  const similarRows = []
  for (const { kind, v, d } of matches) {
    const lines = v.map(x => V[x])
    const rows = d.map(x => D[x])
    if (kind === 'similar') {
      const [line] = lines
      const [row] = rows
      const own = review.text.get(line.text)
      similarRows.push({ row: row.i, default: row.text, version: line.text, start: row.start, score: Number(similarity(line.key, row.key).toFixed(2)), reviewed: own ? 'version text' : review.keep.has(line.text) ? 'default text' : null })
      const entry = { row: row.i }
      if (own) {
        entry.text = line.text
        const translation = own.translation ?? line.line.translation
        if (translation) entry.translation = translation
        if (own.romaji) entry.romaji = own.romaji
        if (line.line.segments?.length) entry.segments = line.line.segments
        if (line.line.performerIds?.length) entry.performerIds = line.line.performerIds
      } else {
        const ids = unionOf(line.line)
        if (ids.length) entry.performerIds = ids
      }
      if (entry.segments || entry.performerIds || entry.text) singers.push(entry)
      continue
    }
    if (kind === 'spread') {
      const ids = unionOf(lines[0].line)
      if (ids.length) for (const row of rows) singers.push({ row: row.i, performerIds: ids })
      continue
    }
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
  const unmatched = V.filter(x => !usedV.has(x.i)).map((x) => {
    const near = D.filter(d => meet(x, d, 1.5)).map(d => ({ row: d.i, start: d.start, text: d.text }))
    return { text: x.text, start: x.start, end: x.end, reviewed: review.keep.has(x.text) ? 'left out' : null, defaultRowsAtThatTime: near }
  })
  const counts = {}
  for (const { kind } of matches) counts[kind] = (counts[kind] || 0) + 1
  const { lines: _lines, credits: _credits, ...rest } = version
  return { version: { ...rest, singers }, unmatched, similar: similarRows, counts, lines: n }
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
  const fromAt = process.argv.indexOf('--from')
  const from = fromAt >= 0 ? process.argv[fromAt + 1] : null
  const report = []
  let changed = 0
  for (const folder of (await readdir(path.join(root, 'lyrics'))).sort()) {
    if (!/^\d+$/.test(folder)) continue
    const relative = `lyrics/${folder}/lyrics.json`
    const file = path.join(root, relative)
    const body = await readFile(file, 'utf8')
    const data = JSON.parse(body)
    if (!data.versions?.length) continue
    let timed = new Map(data.versions.filter(v => v.lines).map(v => [v.vocalId, v]))
    if (from) {
      const old = JSON.parse(execFileSync('git', ['-C', root, 'show', `${from}:${relative}`], { encoding: 'utf8', maxBuffer: 1 << 28 }))
      timed = new Map((old.versions || []).filter(v => v.lines).map(v => [v.vocalId, v]))
    }
    if (!timed.size) continue
    let reviewed = {}
    try {
      reviewed = JSON.parse(await readFile(path.join(root, 'lyrics', folder, 'versions.reviewed.json'), 'utf8')).vocals || {}
    } catch (error) {
      if (error.code !== 'ENOENT') throw error
    }
    data.versions = data.versions.map((version) => {
      const source = timed.get(version.vocalId)
      if (!source) return version
      const result = unifyVersion(data, source, reviewOf(reviewed[version.vocalId]))
      report.push({ musicId: data.musicId, vocalId: version.vocalId, lines: result.lines, singers: result.version.singers.length, matched: result.counts, similar: result.similar, unmatched: result.unmatched })
      return result.version
    })
    if (write) {
      await writeFile(file, replaceValue(body, 'versions', data.versions))
      changed++
    }
  }
  const total = kind => report.reduce((sum, r) => sum + (r.matched[kind] || 0), 0)
  const similar = report.flatMap(r => r.similar.map(s => ({ musicId: r.musicId, vocalId: r.vocalId, ...s })))
  const unmatched = report.flatMap(r => r.unmatched.map(u => ({ musicId: r.musicId, vocalId: r.vocalId, ...u })))
  const open = list => list.filter(item => !item.reviewed).length
  console.log(JSON.stringify({ versions: report.length, lines: report.reduce((n, r) => n + r.lines, 0), exact: total('exact'), reordered: total('reordered'), joined: total('joined'), spread: total('spread'), similar: similar.length, unmatched: unmatched.length, unreviewed: open(similar) + open(unmatched), files: changed }))
  if (process.argv.includes('--verbose')) {
    for (const s of similar) console.log('similar', JSON.stringify(s))
    for (const u of unmatched) console.log('unmatched', JSON.stringify(u))
  }
  if (write) {
    await writeFile(path.join(root, 'reports', 'version-singers.json'), JSON.stringify({
      note: 'Additional versions share the default timeline. Their timed lines became singer assignments on default rows: same text in order, same text out of order, joined runs, reviewed stretches, then similar text at the same time (singers only unless reviewed in lyrics/<id>/versions.reviewed.json). Entries of `similar` and `unmatched` whose `reviewed` is null need a person to check.',
      maxAlignDriftSec: MAX_ALIGN_DRIFT_SEC, minSimilarity: MIN_SIMILARITY, similar, unmatched, versions: report.map(({ similar: _s, unmatched: _u, ...rest }) => rest),
    }, null, 1) + '\n')
  }
}
