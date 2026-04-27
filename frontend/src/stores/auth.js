import { computed, reactive } from 'vue'
import authApi from '@/api/auth'
import {
  getStoredToken,
  setStoredToken,
  setUnauthorizedHandler
} from '@/api/client'

const state = reactive({
  user: null,
  ready: false,
  initPromise: null
})

setUnauthorizedHandler(() => {
  state.user = null
})

async function init() {
  if (state.ready) return
  if (state.initPromise) return state.initPromise

  state.initPromise = (async () => {
    const token = getStoredToken()
    if (!token) return
    try {
      const { user } = await authApi.me()
      state.user = user
    } catch (_e) {
      setStoredToken(null)
      state.user = null
    }
  })()

  try {
    await state.initPromise
  } finally {
    state.ready = true
    state.initPromise = null
  }
}

async function login(email, password) {
  const { user, token } = await authApi.login({ email, password })
  setStoredToken(token)
  state.user = user
  return user
}

async function register(email, password) {
  const { user, token } = await authApi.register({ email, password })
  setStoredToken(token)
  state.user = user
  return user
}

async function loginWithGoogle(idToken) {
  const { user, token } = await authApi.google({ idToken })
  setStoredToken(token)
  state.user = user
  return user
}

async function logout() {
  try {
    await authApi.logout()
  } catch (_e) {
    /* server-side has no state, ignore */
  }
  setStoredToken(null)
  state.user = null
}

async function refresh() {
  if (!getStoredToken()) return null
  try {
    const { user } = await authApi.me()
    state.user = user
    return user
  } catch (_e) {
    return state.user
  }
}

export function useAuth() {
  return {
    user: computed(() => state.user),
    isAuthenticated: computed(() => state.user !== null),
    ready: computed(() => state.ready),
    init,
    login,
    register,
    loginWithGoogle,
    logout,
    refresh
  }
}
