import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5001'

const TOKEN_STORAGE_KEY = 'promptpackage_token'
// Older builds stored the token under this key; migrate once then forget.
const LEGACY_TOKEN_STORAGE_KEYS = ['imrockey_token']

function migrateLegacyToken() {
  try {
    if (localStorage.getItem(TOKEN_STORAGE_KEY)) return
    for (const k of LEGACY_TOKEN_STORAGE_KEYS) {
      const legacy = localStorage.getItem(k)
      if (legacy) {
        localStorage.setItem(TOKEN_STORAGE_KEY, legacy)
        localStorage.removeItem(k)
        return
      }
    }
  } catch (_e) {
    /* ignore storage errors */
  }
}

// Run once at module-load so subsequent reads see the migrated key.
migrateLegacyToken()

const apiClient = axios.create({
  baseURL,
  timeout: 15000,
  withCredentials: false,
  headers: {
    'Content-Type': 'application/json'
  }
})

let unauthorizedHandler = null

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn
}

export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY) || null
  } catch (_e) {
    return null
  }
}

export function setStoredToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch (_e) {
    /* ignore storage errors */
  }
}

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken()
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    if (status === 401) {
      setStoredToken(null)
      if (unauthorizedHandler) {
        try {
          unauthorizedHandler(error)
        } catch (_e) {
          /* never crash the rejection chain */
        }
      }
    }
    return Promise.reject(error)
  }
)

export default apiClient
