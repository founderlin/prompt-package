import apiClient from './client'

export const memoriesApi = {
  listForProject(projectId) {
    return apiClient
      .get(`/api/projects/${projectId}/memories`)
      .then((r) => r.data)
  },
  listForConversation(conversationId) {
    return apiClient
      .get(`/api/conversations/${conversationId}/memories`)
      .then((r) => r.data)
  },
  remove(memoryId) {
    return apiClient
      .delete(`/api/memories/${memoryId}`)
      .then((r) => r.data)
  }
}

export default memoriesApi
