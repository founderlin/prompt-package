/**
 * Per-user *frontend* preference for the default Wrap model.
 *
 * The backend has its own ``DEFAULT_MODEL`` (see
 * ``backend/app/services/wrap_memory/settings.py``) used as the
 * absolute fallback and as the resolution target for Routine Wrap's
 * ``use-global-default``. This helper layers a **client-side**
 * preference on top so the user can tweak the default model that
 * Quick / Advanced wrap dialogs pre-select, without us having to
 * round-trip through a new persistence endpoint.
 *
 * Why localStorage and not a server-side ``User.default_wrap_model``
 * column?
 *
 * * Scope: this is a UI-default knob, not a security or billing
 *   boundary. The server still validates every request against the
 *   ``WrapModel`` enum, so a stale client value can never escalate
 *   into a "wrong model went to the LLM" bug.
 * * Migration cost: no schema change → no migration script → safe to
 *   ship under the "small UX polish" budget for this milestone.
 *
 * When we eventually want this to travel across devices, swap the
 * storage backend out — every consumer reads through these helpers,
 * not directly off ``localStorage``.
 */

const STORAGE_KEY = 'wrap-memory:default-model'

// Keep in sync with backend ``WrapModel`` enum values.
export const WRAP_MODELS = [
  {
    id: 'deepseek-v4-flash',
    label: 'DeepSeek V4 Flash',
    hint: 'Fast & cheap (default)'
  },
  {
    id: 'gemini-3.1-flash',
    label: 'Gemini 3.1 Flash',
    hint: 'Best for long transcripts'
  },
  {
    id: 'gpt-5.4-nano',
    label: 'GPT 5.4 Nano',
    hint: 'Strong reasoning, slower'
  }
]

const VALID_IDS = new Set(WRAP_MODELS.map((m) => m.id))

// The hard-coded fallback if the user has never picked anything.
// Mirrors backend settings.DEFAULT_MODEL so the two ends agree on
// "what does 'default' mean" before any user action.
export const FALLBACK_WRAP_MODEL = 'deepseek-v4-flash'

/**
 * Read the user's preferred default Wrap model.
 *
 * Returns the fallback when there's no stored value, when the stored
 * value is no longer a valid enum (e.g. an obsolete model was
 * removed), or when ``localStorage`` is unavailable (private
 * browsing on some browsers).
 */
export function getDefaultWrapModel() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw && VALID_IDS.has(raw)) return raw
  } catch (_err) {
    /* fall through to the safe default */
  }
  return FALLBACK_WRAP_MODEL
}

/**
 * Write the user's preferred default Wrap model.
 *
 * Silently no-ops on invalid input (so a bad enum from a stale dropdown
 * can't poison the store) and on ``localStorage`` errors (private
 * browsing, quota exhaustion, etc.).
 */
export function setDefaultWrapModel(value) {
  if (!value || !VALID_IDS.has(value)) return false
  try {
    window.localStorage.setItem(STORAGE_KEY, value)
    return true
  } catch (_err) {
    return false
  }
}

export default {
  WRAP_MODELS,
  FALLBACK_WRAP_MODEL,
  getDefaultWrapModel,
  setDefaultWrapModel
}
