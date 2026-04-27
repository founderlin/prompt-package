import apiClient from './client'

export const chatApi = {
  listAllConversations({ limit } = {}) {
    const params = {}
    if (limit != null) params.limit = limit
    return apiClient
      .get('/api/conversations', { params })
      .then((r) => r.data)
  },
  listConversations(projectId) {
    return apiClient
      .get(`/api/projects/${projectId}/conversations`)
      .then((r) => r.data)
  },
  createConversation(projectId, payload = {}) {
    return apiClient
      .post(`/api/projects/${projectId}/conversations`, payload)
      .then((r) => r.data)
  },
  getConversation(conversationId) {
    return apiClient
      .get(`/api/conversations/${conversationId}`)
      .then((r) => r.data)
  },
  updateConversation(conversationId, patch) {
    return apiClient
      .patch(`/api/conversations/${conversationId}`, patch)
      .then((r) => r.data)
  },
  deleteConversation(conversationId) {
    return apiClient
      .delete(`/api/conversations/${conversationId}`)
      .then((r) => r.data)
  },
  listMessages(conversationId) {
    return apiClient
      .get(`/api/conversations/${conversationId}/messages`)
      .then((r) => r.data)
  },
  sendMessage(conversationId, { content, model, provider }) {
    const body = { content, model }
    if (provider) body.provider = provider
    return apiClient
      .post(`/api/conversations/${conversationId}/messages`, body)
      .then((r) => r.data)
  },
  summarizeConversation(conversationId, { model } = {}) {
    const body = {}
    if (model) body.model = model
    return apiClient
      .post(`/api/conversations/${conversationId}/summarize`, body)
      .then((r) => r.data)
  }
}

export default chatApi
