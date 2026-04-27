/**
 * Tiny human-friendly time helpers.
 *
 * Centralised here so every view shows the same "5h ago" / locale string
 * instead of each view re-implementing the same logic (diff in five
 * places at one point during the MVP).
 */

const SECOND = 1_000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/**
 * Returns a short, English relative-time label (e.g. "just now", "5m ago",
 * "3d ago") for the given ISO/Date input. Falls back to a locale date
 * string for anything older than ~30 days. Returns "" when input is
 * empty / unparseable.
 */
export function relativeTime(input) {
  if (!input) return ''
  const ts = input instanceof Date ? input.getTime() : new Date(input).getTime()
  if (Number.isNaN(ts)) return ''

  const diff = Date.now() - ts
  if (diff < MINUTE) return 'just now'
  if (diff < HOUR) {
    const min = Math.round(diff / MINUTE)
    return `${min}m ago`
  }
  if (diff < DAY) {
    const hr = Math.round(diff / HOUR)
    return `${hr}h ago`
  }
  if (diff < 30 * DAY) {
    const day = Math.round(diff / DAY)
    return `${day}d ago`
  }
  try {
    return new Date(ts).toLocaleDateString()
  } catch (_e) {
    return ''
  }
}

/**
 * Locale-aware "Apr 25, 2026, 11:03 AM"-style timestamp. Used in
 * Settings + Context Pack detail where we want a precise marker, not
 * a relative one. Returns "" on invalid input.
 */
export function formatDateTime(input) {
  if (!input) return ''
  const date = input instanceof Date ? input : new Date(input)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return date.toLocaleString()
  } catch (_e) {
    return date.toISOString()
  }
}

export default { relativeTime, formatDateTime }
