import apiClient from './client'

/**
 * Bla Note API client.
 *
 * Endpoints (see backend/app/routes/{projects,bla_notes}.py):
 *   GET    /api/projects/:projectId/notes       — list notes in project
 *   POST   /api/projects/:projectId/notes       — create a note
 *   GET    /api/notes/:noteId                   — fetch one
 *   PATCH  /api/notes/:noteId                   — update
 *   DELETE /api/notes/:noteId                   — delete
 *
 * Response bodies are returned unwrapped so callers choose which key
 * to read (`notes`, `note`, `total`, etc.), matching the other API
 * modules in this codebase.
 */

/**
 * List notes in a project with optional search + pagination.
 *
 * @param {number|string} projectId
 * @param {object} [params]
 * @param {string} [params.keyword] - fuzzy match across title/content/tags
 * @param {string} [params.tag]     - exact tag match
 * @param {number} [params.limit=50]
 * @param {number} [params.offset=0]
 */
function listBlaNotes(projectId, params = {}) {
  const q = {}
  if (params.keyword) q.keyword = params.keyword
  if (params.tag) q.tag = params.tag
  if (params.limit != null) q.limit = params.limit
  if (params.offset != null) q.offset = params.offset
  return apiClient
    .get(`/api/projects/${projectId}/notes`, { params: q })
    .then((r) => r.data)
}

/**
 * Create a note in a project.
 * @param {number|string} projectId
 * @param {{ title: string, content?: string, tags?: string[] | string }} payload
 */
function createBlaNote(projectId, payload = {}) {
  return apiClient
    .post(`/api/projects/${projectId}/notes`, payload)
    .then((r) => r.data)
}

/**
 * Fetch a single note (includes full content).
 * @param {number|string} noteId
 */
function getBlaNote(noteId) {
  return apiClient.get(`/api/notes/${noteId}`).then((r) => r.data)
}

/**
 * Partial update.
 *   - Absent keys untouched.
 *   - `title: ""` is rejected server-side.
 *   - `tags: null` or `tags: []` clears all tags.
 */
function updateBlaNote(noteId, patch = {}) {
  return apiClient.patch(`/api/notes/${noteId}`, patch).then((r) => r.data)
}

/**
 * Delete a note.
 */
function deleteBlaNote(noteId) {
  return apiClient.delete(`/api/notes/${noteId}`).then((r) => r.data)
}

export const blaNotesApi = {
  list: listBlaNotes,
  listBlaNotes,
  create: createBlaNote,
  createBlaNote,
  get: getBlaNote,
  getBlaNote,
  update: updateBlaNote,
  updateBlaNote,
  remove: deleteBlaNote,
  deleteBlaNote
}

export {
  listBlaNotes,
  createBlaNote,
  getBlaNote,
  updateBlaNote,
  deleteBlaNote
}

export default blaNotesApi
