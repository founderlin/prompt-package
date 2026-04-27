<template>
  <header class="app-header">
    <div class="app-header__left">
      <h1 class="app-header__title">{{ title }}</h1>
      <p v-if="subtitle" class="app-header__subtitle">{{ subtitle }}</p>
    </div>

    <div class="app-header__right" ref="menuRef">
      <button
        v-if="auth.isAuthenticated.value"
        class="user-menu__trigger"
        type="button"
        @click="toggleMenu"
        :aria-expanded="menuOpen"
      >
        <span class="user-menu__avatar" aria-hidden="true">{{ initial }}</span>
        <span class="user-menu__email">{{ auth.user.value?.email }}</span>
        <span class="user-menu__caret" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </span>
      </button>

      <span v-else class="chip">Not signed in</span>

      <div v-if="menuOpen" class="user-menu__dropdown" role="menu">
        <div class="user-menu__info">
          <span class="user-menu__info-label">Signed in as</span>
          <span class="user-menu__info-email">{{ auth.user.value?.email }}</span>
        </div>
        <hr class="user-menu__divider" />
        <button
          class="user-menu__item"
          type="button"
          role="menuitem"
          @click="goToSettings"
        >
          <span class="user-menu__icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .4 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.4 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .4-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.4-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.4 1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.4l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.4 1.9 1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
            </svg>
          </span>
          Settings
        </button>
        <button
          class="user-menu__item user-menu__item--danger"
          type="button"
          role="menuitem"
          @click="onLogout"
          :disabled="loggingOut"
        >
          <span class="user-menu__icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </span>
          {{ loggingOut ? 'Signing out…' : 'Sign out' }}
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuth()

const title = computed(() => route.meta?.title || 'IMROCKEY')
const subtitle = computed(() => route.meta?.subtitle || '')

const menuOpen = ref(false)
const menuRef = ref(null)
const loggingOut = ref(false)

const initial = computed(() => {
  const e = auth.user.value?.email || ''
  return e ? e[0].toUpperCase() : '?'
})

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function closeMenu() {
  menuOpen.value = false
}

function goToSettings() {
  closeMenu()
  router.push({ name: 'settings' })
}

async function onLogout() {
  loggingOut.value = true
  try {
    await auth.logout()
    closeMenu()
    router.replace({ name: 'login' })
  } finally {
    loggingOut.value = false
  }
}

function onDocumentClick(event) {
  if (!menuOpen.value) return
  if (menuRef.value && !menuRef.value.contains(event.target)) {
    closeMenu()
  }
}

function onKeydown(event) {
  if (event.key === 'Escape') closeMenu()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.app-header {
  height: var(--layout-header-h);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-6);
  position: sticky;
  top: 0;
  z-index: 5;
}

.app-header__left {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.app-header__title {
  font-size: var(--text-lg);
  font-weight: 500;
  margin: 0;
  letter-spacing: 0.2px;
}

.app-header__subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0;
}

.app-header__right {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.user-menu__trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 10px 4px 4px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}

.user-menu__trigger:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-border-strong);
}

.user-menu__avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.user-menu__email {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-menu__caret {
  display: inline-flex;
  color: var(--color-text-muted);
}

.user-menu__dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 240px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-3);
  padding: var(--space-2);
  z-index: 20;
}

.user-menu__info {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-menu__info-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.user-menu__info-email {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: 500;
  word-break: break-all;
}

.user-menu__divider {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: var(--space-1) 0;
}

.user-menu__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  background: transparent;
  border: none;
  padding: 9px var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
}

.user-menu__item:hover:not(:disabled) {
  background: var(--color-surface-hover);
}

.user-menu__item:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.user-menu__item--danger {
  color: var(--color-error);
}

.user-menu__item--danger:hover:not(:disabled) {
  background: var(--color-error-soft);
}

.user-menu__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: currentColor;
}
</style>
