/**
 * Human-friendly byte size formatting.
 *
 * Mirrors the backend ``format_bytes`` (Phase 1) so the dashboard
 * "428 KB" reading lines up exactly with what the server reports.
 * We use the same 1024-based steps + 1-decimal rounding for KB / MB
 * and an integer-only fast path for B.
 */

const KB = 1024
const MB = 1024 * 1024
const GB = 1024 * 1024 * 1024

/**
 * Return a short label for a byte count.
 *
 * Examples:
 *   formatBytes(0)         // "0 B"
 *   formatBytes(900)       // "900 B"
 *   formatBytes(1024)      // "1 KB"
 *   formatBytes(1536)      // "1.5 KB"
 *   formatBytes(5_242_880) // "5 MB"
 *
 * @param {number} bytes  Raw byte count (non-negative).
 * @returns {string}      Formatted label.
 */
export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return '0 B'
  const n = Math.max(0, Math.trunc(bytes))
  if (n < KB) return `${n} B`
  if (n < MB) return `${trim(n / KB)} KB`
  if (n < GB) return `${trim(n / MB)} MB`
  return `${trim(n / GB)} GB`
}

// Drop trailing .0 / 0 so "1.0 KB" reads as "1 KB" but "1.5 KB" stays
// intact. Keeps the dashboard line compact ("12 wraps · 428 KB").
function trim(value) {
  const fixed = value.toFixed(1)
  return fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed
}

export default { formatBytes }
