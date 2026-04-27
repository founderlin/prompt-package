/**
 * Model selections API client.
 *
 * A user curates, per provider, which model ids should appear in the
 * chat composer's model picker. These calls back the per-provider
 * cards on the Settings page.
 */

import apiClient from './client'

export const modelSelectionsApi = {
  list() {
    return apiClient.get('/api/settings/models').then((r) => r.data)
  },

  replace(provider, models) {
    // ``models`` is an array of strings OR objects { model_id, label }.
    return apiClient
      .put(`/api/settings/models/${provider}`, { models })
      .then((r) => r.data)
  },

  add(provider, { modelId, label } = {}) {
    return apiClient
      .post(`/api/settings/models/${provider}`, {
        model_id: modelId,
        label: label || null
      })
      .then((r) => r.data)
  },

  remove(provider, modelId) {
    return apiClient
      .delete(
        `/api/settings/models/${provider}/${encodeURIComponent(modelId)}`
      )
      .then((r) => r.data)
  }
}

export default modelSelectionsApi
