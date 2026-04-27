/**
 * Providers API client (R14).
 *
 * Wraps the new ``/api/settings/providers`` endpoints. Plaintext API
 * keys are sent over HTTPS only; never logged here. axios doesn't log
 * request bodies, and we don't either.
 */

import apiClient from './client'

export const providersApi = {
  list() {
    return apiClient.get('/api/settings/providers').then((r) => r.data)
  },

  status(provider) {
    return apiClient
      .get(`/api/settings/providers/${provider}`)
      .then((r) => r.data)
  },

  saveKey(provider, { apiKey, skipVerify = false }) {
    return apiClient
      .put(`/api/settings/providers/${provider}/key`, {
        api_key: apiKey,
        skip_verify: skipVerify
      })
      .then((r) => r.data)
  },

  deleteKey(provider) {
    return apiClient
      .delete(`/api/settings/providers/${provider}/key`)
      .then((r) => r.data)
  },

  testKey(provider, { apiKey } = {}) {
    const body = apiKey ? { api_key: apiKey } : {}
    return apiClient
      .post(`/api/settings/providers/${provider}/test`, body)
      .then((r) => r.data)
  }
}

export default providersApi
