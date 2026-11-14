import assert from 'node:assert/strict'

export function defaultRows(data) {
  if (data.format === 'bilingual_json') return data.lines
  const rows = [], cues = []
  for (const row of data.lrc.split(/\r?\n/)) {
    const text = row.replace(/\[\d+:\d+(?:\.\d+)?\]/g, '').trim()
    for (const [, m, s] of row.matchAll(/\[(\d+):(\d+(?:\.\d+)?)\]/g)) {
      const cueStart = Number(m)*60+Number(s)
      if (cueStart > data.duration) continue
      cues.push(cueStart)
      if (text) rows.push({text, cueStart})
    }
  }
  cues.sort((a,b)=>a-b)
  return rows.sort((a,b)=>a.cueStart-b.cueStart).map(row => ({...row, end:cues.find(cue => cue > row.cueStart) ?? data.duration}))
}

/** The default rows with the timing they play at: line timings, then word timing, over the raw LRC cue. */
export function defaultTimeline(data) {
  const base = defaultRows(data)
  return data.format === 'bilingual_json' ? base : base.map(row => {
    const matches = line => Math.abs(line.cueStart - row.cueStart) < 0.001 && line.text === row.text
    return { ...row, start: row.cueStart, end: row.end,
      ...(data.lineTimings || []).find(matches), ...(data.wordLines || []).find(matches) }
  })
}

export function validateVersions(data) {
  const base = defaultRows(data), ids = new Set([data.vocalId].filter(Number.isInteger))
  const knownDefault = new Set((data.performers || []).map(p => p.performerId))
  let previousDefault = -1
  for (const line of defaultTimeline(data)) {
    assert.ok(Number.isFinite(line.start) && line.start >= 0 && line.start >= previousDefault, 'default timeline order')
    // Existing exports round some decoded durations to five decimal places.
    assert.ok(Number.isFinite(line.end) && line.end >= line.start && line.end <= data.duration + 0.00001, 'default timeline bounds')
    previousDefault = line.start
    for (const id of [...(line.performerIds || []), ...(line.segments || []).flatMap(s => s.performerIds || [])]) assert.ok(knownDefault.has(id), 'unknown default performer')
  }
  const timingKeys = new Set()
  for (const line of data.lineTimings || []) {
    assert.ok(base.some(row => row.cueStart === line.cueStart && row.text === line.text), 'unmatched lineTimings')
    const key = JSON.stringify([line.cueStart, line.text])
    assert.ok(!timingKeys.has(key), 'duplicate lineTimings')
    timingKeys.add(key)
  }
  for (const p of data.performers || []) {
    const match = /^歌唱者-(\d+)$/.exec(p.performerId)
    if (match && p.characterId != null) assert.equal(p.characterId, Number(match[1]))
  }
  for (const version of data.versions || []) {
    assert.ok(Number.isInteger(version.vocalId) && !ids.has(version.vocalId), 'duplicate/invalid vocal')
    ids.add(version.vocalId)
    assert.ok(typeof version.assetbundle === 'string' && version.assetbundle.length)
    assert.ok(Number.isFinite(version.duration) && version.duration > 0)
    assert.ok(['A','B','C','D'].includes(version.source))
    assert.ok(Array.isArray(version.performers))
    const performers = new Set(version.performers.map(p=>p.performerId))
    assert.equal(performers.size, version.performers.length)
    for (const p of version.performers) {
      assert.equal(typeof p.name, 'string')
      const match = /^歌唱者-(\d+)$/.exec(p.performerId)
      if (match) assert.equal(p.characterId, Number(match[1]))
      else assert.equal(p.characterId, null)
    }
    // Every rendition is sung to the same backing track: it shares the default timeline and
    // says who sings which default row (and, on reviewed rows, other words). No timing of its own.
    assert.equal(version.lines, undefined, 'versions keep singers only (run unify-version-singers.mjs)')
    assert.equal(version.credits, undefined, 'versions show the default text and its credits')
    assert.ok(Array.isArray(version.singers))
    let previous = -1
    for (const entry of version.singers) {
      assert.deepEqual(Object.keys(entry).filter(k => !['row', 'segments', 'performerIds', 'text', 'translation'].includes(k)), [], 'singer entries carry no timing')
      assert.ok(Number.isInteger(entry.row) && entry.row > previous && entry.row < base.length, 'singer rows in order, once each, on default rows')
      previous = entry.row
      assert.ok(entry.segments?.length || entry.performerIds?.length || entry.text, 'empty singer entry')
      // A row the version sings with other words (reviewed) shows them instead of the default text.
      if (entry.text !== undefined) assert.ok(typeof entry.text === 'string' && entry.text && entry.text !== base[entry.row].text, 'version text must differ from the default row')
      if (entry.translation !== undefined) assert.ok(entry.text !== undefined && typeof entry.translation === 'string', 'translation only with version text')
      for (const id of entry.performerIds || []) assert.ok(performers.has(id), 'unknown performer')
      if (entry.segments) {
        assert.equal(entry.segments.map(s => s.text).join(''), entry.text ?? base[entry.row].text)
        for (const segment of entry.segments) for (const id of segment.performerIds || []) assert.ok(performers.has(id), 'unknown segment performer')
      }
    }
  }
}
