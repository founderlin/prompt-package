/**
 * Wrap (project memory) API client.
 *
 * Backed by Phase 3 + 4 + 5 + 6 routes:
 *   - POST /api/projects/:pid/conversations/:cid/wraps/quick-draft
 *   - POST /api/projects/:pid/conversations/:cid/wraps/advanced-draft
 *   - POST /api/projects/:pid/conversations/:cid/wraps/routine-draft
 *   - POST /api/projects/:pid/wraps
 *   - GET  /api/projects/:pid/wraps/routine-config
 *   - PUT  /api/projects/:pid/wraps/routine-config
 *   - GET  /api/projects/:pid/wraps/routine-status
 *   - POST /api/projects/:pid/wraps/routine-dismiss
 *   - POST /api/projects/:pid/wraps/routine-mark-run
 *   - GET  /api/projects/:pid/wraps/stats         (Phase 6)
 *   - GET  /api/wraps/stats                       (Phase 6, batch)
 *
 * These calls hit the LLM (drafts) or write the filesystem (saves),
 * so we widen the per-call timeout beyond the default 15s the global
 * axios instance uses. We mirror the same 120s ceiling already used
 * by chat completions in @/api/wrapUp.js to stay consistent.
 *
 * Shape of the draft response (camelCase, mirrors WrapDraftBundle):
 *
 *   {
 *     draft: {
 *       analysis: WrapAnalysisResult,
 *       markdown: string,
 *       suggestedFilename: string,
 *       savePathRelative: string,
 *       mode: 'quick' | 'advanced' | 'routine',
 *       model: 'deepseek-v4-flash' | 'gemini-3.1-flash' | 'gpt-5.4-nano',
 *       usedMock: boolean
 *     }
 *   }
 *
 * Shape of the save response (mirrors SavedWrap):
 *
 *   {
 *     wrap: {
 *       projectId: number,
 *       filename: string,
 *       absolutePath: string,
 *       relativePath: string,
 *       bytesWritten: number
 *     }
 *   }
 */

import apiClient from './client'

// Wrap-related calls can stall behind LLM round-trips. Save is mostly
// disk I/O so it's quick, but reuse the same 120s ceiling for
// simplicity — operators can lower it later via a custom client.
const WRAP_TIMEOUT_MS = 120_000

export const wrapsApi = {
  /**
   * Generate a Quick Wrap draft for a conversation. The server does
   * NOT persist anything — the user must call ``save`` separately
   * after reviewing the preview.
   */
  /**
   * @param {number} projectId
   * @param {number} conversationId
   * @param {object} [opts]
   * @param {string} [opts.model]  Optional WrapModel id; when omitted the
   *                               server falls back to its DEFAULT_MODEL.
   *                               Used by the Settings → Wrap model
   *                               preference to override the default.
   */
  draftQuick(projectId, conversationId, { model } = {}) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    if (!conversationId) {
      return Promise.reject(new Error('conversationId is required'))
    }
    const payload = {}
    if (model) payload.model = model
    return apiClient
      .post(
        `/api/projects/${projectId}/conversations/${conversationId}/wraps/quick-draft`,
        payload,
        { timeout: WRAP_TIMEOUT_MS }
      )
      .then((r) => r.data)
  },

  /**
   * Generate an Advanced Wrap draft. The dialog UI lets the user pick
   * a model + tweak per-bucket filter actions before kicking off the
   * draft; everything else (analysis, Markdown rendering, save path)
   * matches the Quick draft response shape so the frontend can render
   * both with the same components.
   *
   * @param {number} projectId
   * @param {number} conversationId
   * @param {object} options
   * @param {string} options.model         One of the WrapModel enum values.
   * @param {object} options.filters       Map of bucket → action.
   *                                       (codeBlocks/images/promptText/logs/offTopic)
   *                                       Missing keys fall back to defaults.
   * @param {string} [options.userInstruction]
   */
  draftAdvanced(projectId, conversationId, { model, filters, userInstruction } = {}) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    if (!conversationId) {
      return Promise.reject(new Error('conversationId is required'))
    }
    const payload = {}
    if (model) payload.model = model
    if (filters && typeof filters === 'object') payload.filters = filters
    if (userInstruction) payload.userInstruction = userInstruction
    return apiClient
      .post(
        `/api/projects/${projectId}/conversations/${conversationId}/wraps/advanced-draft`,
        payload,
        { timeout: WRAP_TIMEOUT_MS }
      )
      .then((r) => r.data)
  },

  /**
   * Persist a (possibly edited) Markdown wrap to disk. ``filename``
   * should be the ``suggestedFilename`` from the draft response, or
   * a user-edited variant that still ends in ``.md`` and is a plain
   * file name (the backend will reject path traversal).
   */
  save(projectId, { markdown, filename }) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    if (!markdown || !markdown.trim()) {
      return Promise.reject(new Error('markdown is required'))
    }
    return apiClient
      .post(
        `/api/projects/${projectId}/wraps`,
        { markdown, filename },
        { timeout: WRAP_TIMEOUT_MS }
      )
      .then((r) => r.data)
  },

  // -------------------------------------------------------------------------
  // Routine Wrap (Phase 5).
  //
  // The status + config calls are cheap (~ DB hits) so they reuse the
  // axios global default timeout. ``draftRoutine`` runs an LLM call so
  // we widen the ceiling to match draftQuick/Advanced.

  /**
   * Fetch the routine wrap configuration for a project. Returns the
   * server-rendered defaults when no row exists yet, so the caller
   * never has to special-case "not configured".
   */
  getRoutineConfig(projectId) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    return apiClient
      .get(`/api/projects/${projectId}/wraps/routine-config`)
      .then((r) => r.data)
  },

  /**
   * Upsert routine wrap configuration. ``review_required`` and
   * ``auto_save`` are always clamped to the Phase 5 invariants
   * server-side, so callers can omit them (UI never exposes them).
   */
  updateRoutineConfig(projectId, config) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    return apiClient
      .put(`/api/projects/${projectId}/wraps/routine-config`, config || {})
      .then((r) => r.data)
  },

  /**
   * Combined "should the banner fire" probe. Returns
   *   { config, isDue, hasNewActivity, shouldPrompt, now }
   * ``shouldPrompt`` is the bit the banner actually checks; the
   * other flags help compose informative empty states.
   */
  getRoutineStatus(projectId) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    return apiClient
      .get(`/api/projects/${projectId}/wraps/routine-status`)
      .then((r) => r.data)
  },

  /**
   * User clicked Dismiss on the banner. Stamps ``dismissed_at`` —
   * server mutes the banner for 24h but doesn't touch the cadence
   * anchor (``last_run_at``), so the next interval still fires.
   */
  dismissRoutine(projectId) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    return apiClient
      .post(`/api/projects/${projectId}/wraps/routine-dismiss`)
      .then((r) => r.data)
  },

  /**
   * User completed a Routine save flow. Stamps ``last_run_at`` and
   * clears any prior ``dismissed_at`` so the cadence math resets.
   * Should be called *after* a successful :func:`save` round-trip.
   */
  markRoutineRun(projectId) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    return apiClient
      .post(`/api/projects/${projectId}/wraps/routine-mark-run`)
      .then((r) => r.data)
  },

  /**
   * Generate a Routine Wrap draft. Same response shape as quick /
   * advanced draft so the frontend's Review dialog can render any
   * of them. The server enforces ``review_required=True`` — this
   * call never persists; the caller must follow up with ``save()``
   * and ``markRoutineRun()``.
   */
  draftRoutine(projectId, conversationId) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    if (!conversationId) {
      return Promise.reject(new Error('conversationId is required'))
    }
    return apiClient
      .post(
        `/api/projects/${projectId}/conversations/${conversationId}/wraps/routine-draft`,
        {},
        { timeout: WRAP_TIMEOUT_MS }
      )
      .then((r) => r.data)
  },

  // -------------------------------------------------------------------------
  // Memory stats (Phase 6).
  //
  // Pure disk reads — fast enough to reuse the global axios default
  // timeout. ``getAllStats`` is the only call the dashboard makes
  // for its "Wrap memory" panel.

  /**
   * Single-project stats: ``{ projectId, projectName, wrapCount,
   * memorySizeBytes, lastWrappedAt }``. All-zero / null for projects
   * with no wraps yet (the server never 404s on "empty").
   */
  getStats(projectId) {
    if (!projectId) {
      return Promise.reject(new Error('projectId is required'))
    }
    return apiClient
      .get(`/api/projects/${projectId}/wraps/stats`)
      .then((r) => r.data)
  },

  /**
   * Batch stats: one entry per project the user owns, ordered to
   * match ``Project.updated_at DESC``. Used by the dashboard's
   * "Wrap memory" list.
   */
  getAllStats() {
    return apiClient.get('/api/wraps/stats').then((r) => r.data)
  }
}

export default wrapsApi
