import apiClient from './client'

export function fetchHealth() {
  return apiClient.get('/api/health').then((res) => res.data)
}
