import apiClient from './client'

export const searchApi = {
  /**
   * Cross-project search across messages, memories, and conversations.
   * @param {string} q
   * @param {{ types?: string[], limit?: number }} [options]
   */
  search(q, { types, limit } = {}) {
    const params = new URLSearchParams()
    if (q) params.append('q', q)
    if (limit != null) params.append('limit', String(limit))
    if (Array.isArray(types) && types.length) {
      for (const t of types) {
        if (t) params.append('type', t)
      }
    }
    return apiClient
      .get('/api/search', { params })
      .then((r) => r.data)
  }
}

export default searchApi
