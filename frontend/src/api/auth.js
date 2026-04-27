import apiClient from './client'

export const authApi = {
  register({ email, password }) {
    return apiClient
      .post('/api/auth/register', { email, password })
      .then((r) => r.data)
  },
  login({ email, password }) {
    return apiClient
      .post('/api/auth/login', { email, password })
      .then((r) => r.data)
  },
  logout() {
    return apiClient.post('/api/auth/logout').then((r) => r.data)
  },
  me() {
    return apiClient.get('/api/auth/me').then((r) => r.data)
  },
  // R15 — Google Identity Services. ``idToken`` is what GIS gives us as
  // ``response.credential`` on a successful one-tap / button click.
  google({ idToken }) {
    return apiClient
      .post('/api/auth/google', { id_token: idToken })
      .then((r) => r.data)
  },
  googleConfig() {
    return apiClient.get('/api/auth/google/config').then((r) => r.data)
  }
}

export default authApi
