import apiClient from './client'

/**
 * Context Pack API client.
 *
 * Backend base URL is supplied by `./client.js`; this module only
 * knows about paths + param shapes. Response bodies are returned
 * unwrapped (e.g. `{ context_pack, ... }`) so callers decide which
 * key to read — keeps the wrapper thin.
 *
 * Legacy aliases (`listForProject`, `listRecent`, `generate`, `get`,
 * `update`, `remove`) are preserved so existing views (ProjectDetailView,
 * ProjectChatView, ContextPackView) keep working unchanged.
 */

const LIST_ENDPOINT = '/api/context-packs'
const DETAIL_ENDPOINT = (id) => `${LIST_ENDPOINT}/${id}`
const SOURCES_ENDPOINT = (id) => `${LIST_ENDPOINT}/${id}/sources`

/**
 * List the caller's Context Packs with optional filters.
 *
 * Accepts both camelCase (`projectId`, `sourceType`) and snake_case
 * (`project_id`, `source_type`) for convenience.
 *
 * @param {Object} params
 * @param {string} [params.keyword]
 * @param {number|string} [params.projectId]
 * @param {string} [params.sourceType] - 'project' | 'conversation' | 'note' | 'attachment' | 'mixed'
 * @param {string} [params.visibility] - 'private' (MVP)
 * @param {number} [params.limit=20]
 * @param {number} [params.offset=0]
 * @returns Promise<{ items, total, grand_total, limit, offset, context_packs }>
 */
function listContextPacks(params = {}) {
  const q = {}
  if (params.keyword) q.keyword = params.keyword
  const projectId = params.projectId ?? params.project_id
  if (projectId != null && projectId !== '') q.projectId = projectId
  const sourceType = params.sourceType ?? params.source_type
  if (sourceType) q.sourceType = sourceType
  if (params.visibility) q.visibility = params.visibility
  if (params.limit != null) q.limit = params.limit
  if (params.offset != null) q.offset = params.offset
  return apiClient.get(LIST_ENDPOINT, { params: q }).then((r) => r.data)
}

/**
 * Fetch a single pack (includes body + sources).
 * @param {number|string} packId
 */
function getContextPack(packId) {
  return apiClient.get(DETAIL_ENDPOINT(packId)).then((r) => r.data)
}

/**
 * Create a Context Pack from a user-supplied payload.
 * Payload mirrors the POST /api/context-packs body documented in the
 * route file. Keys accept camelCase from the UI.
 *
 * @param {Object} payload
 * @returns Promise<{ context_pack }>
 */
function createContextPack(payload = {}) {
  return apiClient.post(LIST_ENDPOINT, payload).then((r) => r.data)
}

/**
 * Partial update. Absent keys are untouched; explicit `null` clears
 * a nullable field; `title: ""` is rejected server-side.
 *
 * @param {number|string} packId
 * @param {Object} patch
 */
function updateContextPack(packId, patch = {}) {
  return apiClient.patch(DETAIL_ENDPOINT(packId), patch).then((r) => r.data)
}

/**
 * Delete a pack (source rows cascade on the server).
 * @param {number|string} packId
 */
function deleteContextPack(packId) {
  return apiClient.delete(DETAIL_ENDPOINT(packId)).then((r) => r.data)
}

/**
 * List a pack's provenance rows.
 * @param {number|string} packId
 */
function listContextPackSources(packId) {
  return apiClient.get(SOURCES_ENDPOINT(packId)).then((r) => r.data)
}

/**
 * Tell the server this pack was just used (bumps usage_count +
 * last_used_at). Used by Context Zoo's "Use in new conversation"
 * action so recency / popularity surface without additional
 * plumbing at every call-site.
 * @param {number|string} packId
 */
function registerContextPackUsage(packId) {
  return apiClient
    .post(`${LIST_ENDPOINT}/${packId}/use`)
    .then((r) => r.data)
}

// ---------- Back-compat facade ------------------------------------------
//
// These forward to the existing project-scoped endpoints so legacy
// views keep working. They live alongside the new flat CRUD above.

export const contextPacksApi = {
  // --- New flat CRUD ---------------------------------------------------
  list: listContextPacks,
  listContextPacks,
  get: getContextPack,
  getContextPack,
  create: createContextPack,
  createContextPack,
  update: updateContextPack,
  updateContextPack,
  remove: deleteContextPack,
  deleteContextPack,
  listSources: listContextPackSources,
  listContextPackSources,
  registerUsage: registerContextPackUsage,
  registerContextPackUsage,

  // --- Legacy shapes (kept as-is) --------------------------------------
  listForProject(projectId) {
    return apiClient
      .get(`/api/projects/${projectId}/context-packs`)
      .then((r) => r.data)
  },
  listRecent({ limit } = {}) {
    const params = {}
    if (limit != null) params.limit = limit
    return apiClient.get(LIST_ENDPOINT, { params }).then((r) => r.data)
  },
  generate(projectId, payload = {}) {
    return apiClient
      .post(`/api/projects/${projectId}/context-packs/generate`, payload)
      .then((r) => r.data)
  }
}

// Also export the stand-alone functions so callers can import just
// what they need (`import { listContextPacks } from '@/api/contextPacks'`).
export {
  listContextPacks,
  getContextPack,
  createContextPack,
  updateContextPack,
  deleteContextPack,
  listContextPackSources,
  registerContextPackUsage
}

export default contextPacksApi
