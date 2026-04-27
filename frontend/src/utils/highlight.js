// Render a string with all case-insensitive occurrences of `query` wrapped in
// <mark>…</mark>. Returns an array of segments suitable for `<template v-for>`,
// so we never have to dangerously inject HTML.
//
// Example output for highlightSegments("Hello World", "world"):
//   [{ text: "Hello ", match: false }, { text: "World", match: true }]

export function highlightSegments(text, query) {
  const safeText = text == null ? '' : String(text)
  const safeQuery = query == null ? '' : String(query).trim()
  if (!safeText || !safeQuery) {
    return [{ text: safeText, match: false }]
  }

  const segments = []
  const lowerText = safeText.toLowerCase()
  const lowerQuery = safeQuery.toLowerCase()
  const queryLen = safeQuery.length
  let cursor = 0

  while (cursor < safeText.length) {
    const idx = lowerText.indexOf(lowerQuery, cursor)
    if (idx === -1) {
      segments.push({ text: safeText.slice(cursor), match: false })
      break
    }
    if (idx > cursor) {
      segments.push({ text: safeText.slice(cursor, idx), match: false })
    }
    segments.push({ text: safeText.slice(idx, idx + queryLen), match: true })
    cursor = idx + queryLen
  }

  return segments
}

export default highlightSegments
