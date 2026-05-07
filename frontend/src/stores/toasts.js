/**
 * Tiny app-wide toast/notification store.
 *
 * A single host (<ToastHost/>) mounts once in AppShell and reactively
 * renders whatever is in `state.items`. Any component can call
 * `useToasts().push({ ... })` to show a transient notification that
 * slides in from the top, auto-dismisses after `duration` ms, and can
 * be manually closed via an × button.
 *
 * Design choices
 * --------------
 * - No 3rd-party dep; ~30 LOC of state.
 * - Items carry optional `link` (vue-router `to` object) + `linkText` so
 *   the notification can lead the user to the source of truth (e.g.
 *   the memories panel on the project page).
 * - The same id is used for both the list key and the dismiss timer so
 *   consumers can call `dismiss(id)` without tracking anything themselves.
 */

import { reactive } from 'vue'

const state = reactive({
  items: []
})

const DEFAULT_DURATION = 5000

// Hand-rolled id counter — we only need uniqueness within a session.
let nextId = 1
// Kept outside reactive state so Vue doesn't needlessly track timers.
const timers = new Map()

function push(input) {
  const id = nextId++
  const item = {
    id,
    kind: input.kind || 'success', // 'success' | 'error' | 'info'
    message: String(input.message || ''),
    link: input.link || null, // vue-router `to` location object, optional
    linkText: input.linkText || '',
    // 0 (or negative) = sticky; otherwise auto-dismiss after this many ms.
    duration: Number.isFinite(input.duration) ? input.duration : DEFAULT_DURATION
  }
  state.items.push(item)

  if (item.duration > 0) {
    const timer = setTimeout(() => dismiss(id), item.duration)
    timers.set(id, timer)
  }
  return id
}

function dismiss(id) {
  const idx = state.items.findIndex((t) => t.id === id)
  if (idx !== -1) state.items.splice(idx, 1)
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }
}

function clear() {
  for (const t of timers.values()) clearTimeout(t)
  timers.clear()
  state.items.splice(0, state.items.length)
}

export function useToasts() {
  return {
    items: state.items,
    push,
    dismiss,
    clear
  }
}

export default useToasts
