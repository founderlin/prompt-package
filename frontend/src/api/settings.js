/**
 * Settings API client.
 *
 * Note: we deliberately never `console.log` request payloads here — they
 * may contain a plaintext OpenRouter API key. axios itself does not log
 * payloads, so as long as nothing else touches the body, the key only
 * lives in memory and on the wire to the backend.
 */

import apiClient from './client'

export const settingsApi = {
  getOpenRouterKey() {
    return apiClient.get('/api/settings/openrouter-key').then((r) => r.data)
  },

  saveOpenRouterKey({ apiKey, skipVerify = false }) {
    return apiClient
      .put('/api/settings/openrouter-key', {
        api_key: apiKey,
        skip_verify: skipVerify
      })
      .then((r) => r.data)
  },

  deleteOpenRouterKey() {
    return apiClient.delete('/api/settings/openrouter-key').then((r) => r.data)
  },

  testOpenRouterKey({ apiKey } = {}) {
    const body = apiKey ? { api_key: apiKey } : {}
    return apiClient
      .post('/api/settings/openrouter-key/test', body)
      .then((r) => r.data)
  }
}

export default settingsApi
