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

export function validateVersions(data) {
  const base = defaultRows(data), ids = new Set([data.vocalId].filter(Number.isInteger))
  const knownDefault = new Set((data.performers || []).map(p => p.performerId))
  const defaultTimeline = data.format === 'bilingual_json' ? base : base.map((row, i) => {
    const matches = line => Math.abs(line.cueStart - row.cueStart) < 0.001 && line.text === row.text
    return { ...row, start: row.cueStart, end: row.end,
      ...(data.lineTimings || []).find(matches), ...(data.wordLines || []).find(matches) }
  })
  let previousDefault = -1
  for (const line of defaultTimeline) {
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
    assert.ok(version.lines?.length)
    let previous = -1
    for (const line of version.lines) {
      assert.ok(Number.isFinite(line.start) && line.start >= previous && line.start >= 0, 'nonmonotonic version')
      assert.ok(Number.isFinite(line.end) && line.end > line.start && line.end <= version.duration, 'version bounds')
      previous = line.start
      let text = line.text
      if (line.textRef != null) {
        assert.ok(Number.isInteger(line.textRef) && line.textRef >= 0 && line.textRef < base.length, 'invalid textRef')
        assert.equal(line.text, undefined)
        assert.equal(line.translation, undefined)
        text = base[line.textRef].text
      }
      assert.equal(typeof text, 'string')
      for (const id of line.performerIds || []) assert.ok(performers.has(id), 'unknown performer')
      if (line.segments) {
        assert.equal(line.segments.map(s=>s.text).join(''), text)
        for (const segment of line.segments) for (const id of segment.performerIds || []) assert.ok(performers.has(id), 'unknown segment performer')
      }
      let cursor = 0
      for (const word of line.words || []) {
        assert.ok(Number.isInteger(word.from) && Number.isInteger(word.to) && word.from >= cursor && word.to > word.from && word.to <= text.length)
        assert.ok(Number.isFinite(word.start) && Number.isFinite(word.end) && word.start >= line.start && word.end >= word.start && word.end <= line.end)
        cursor = word.to
      }
    }
  }
}
