import apiClient from './client'

export const projectsApi = {
  list() {
    return apiClient.get('/api/projects').then((r) => r.data)
  },
  get(id) {
    return apiClient.get(`/api/projects/${id}`).then((r) => r.data)
  },
  create({ name, description }) {
    return apiClient
      .post('/api/projects', { name, description })
      .then((r) => r.data)
  },
  update(id, patch) {
    return apiClient.patch(`/api/projects/${id}`, patch).then((r) => r.data)
  },
  remove(id) {
    return apiClient.delete(`/api/projects/${id}`).then((r) => r.data)
  }
}

export default projectsApi
