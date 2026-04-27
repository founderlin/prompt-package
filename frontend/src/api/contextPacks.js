import apiClient from './client'

export const contextPacksApi = {
  listForProject(projectId) {
    return apiClient
      .get(`/api/projects/${projectId}/context-packs`)
      .then((r) => r.data)
  },
  listRecent({ limit } = {}) {
    const params = {}
    if (limit != null) params.limit = limit
    return apiClient
      .get('/api/context-packs', { params })
      .then((r) => r.data)
  },
  get(packId) {
    return apiClient
      .get(`/api/context-packs/${packId}`)
      .then((r) => r.data)
  },
  generate(projectId, payload = {}) {
    return apiClient
      .post(`/api/projects/${projectId}/context-packs/generate`, payload)
      .then((r) => r.data)
  },
  update(packId, patch) {
    return apiClient
      .patch(`/api/context-packs/${packId}`, patch)
      .then((r) => r.data)
  },
  remove(packId) {
    return apiClient
      .delete(`/api/context-packs/${packId}`)
      .then((r) => r.data)
  }
}

export default contextPacksApi
