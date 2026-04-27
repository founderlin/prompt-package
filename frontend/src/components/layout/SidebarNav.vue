<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': collapsed }">
    <div class="sidebar__header">
      <div class="sidebar__brand">
        <div class="brand-logo-wrap">
          <img :src="logo1" alt="Logo part 1" class="logo-img logo-img--1" />
          <img v-if="!collapsed" :src="logo2" alt="Logo part 2" class="logo-img logo-img--2" />
        </div>
      </div>
      <button 
        type="button" 
        class="sidebar__toggle" 
        @click="toggleSidebar"
        :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
      >
        <svg 
          width="20" 
          height="20" 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          stroke-width="2" 
          stroke-linecap="round" 
          stroke-linejoin="round"
          class="toggle-icon"
        >
          <line v-if="!collapsed" x1="18" y1="6" x2="6" y2="18"></line>
          <line v-if="!collapsed" x1="6" y1="6" x2="18" y2="18"></line>
          <line v-if="collapsed" x1="3" y1="12" x2="21" y2="12"></line>
          <line v-if="collapsed" x1="3" y1="6" x2="21" y2="6"></line>
          <line v-if="collapsed" x1="3" y1="18" x2="21" y2="18"></line>
        </svg>
      </button>
    </div>

    <nav class="sidebar__nav" aria-label="Primary">
      <p v-if="!collapsed" class="sidebar__section-title">Workspace</p>
      <div v-else class="sidebar__section-divider"></div>
      <RouterLink
        v-for="item in primaryNav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item) }"
        :title="collapsed ? item.label : ''"
      >
        <span class="nav-item__icon" v-html="item.icon" aria-hidden="true" />
        <span v-if="!collapsed" class="nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <nav class="sidebar__nav sidebar__nav--bottom" aria-label="Secondary">
      <p v-if="!collapsed" class="sidebar__section-title">Account</p>
      <div v-else class="sidebar__section-divider"></div>
      <RouterLink
        v-for="item in secondaryNav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item) }"
        :title="collapsed ? item.label : ''"
      >
        <span class="nav-item__icon" v-html="item.icon" aria-hidden="true" />
        <span v-if="!collapsed" class="nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar__footer">
      <span v-if="!collapsed" class="chip">MVP · v0.1.0</span>
      <span v-else class="dot dot--success"></span>
    </div>
  </aside>
</template>

<script setup>
import { ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import logo1 from '@/assets/logo1.png'
import logo2 from '@/assets/logo2.png'

const route = useRoute()
const collapsed = ref(false)

function toggleSidebar() {
  collapsed.value = !collapsed.value
  // Optional: save preference to localStorage
  localStorage.setItem('sidebar_collapsed', String(collapsed.value))
}

// Restore preference on load
if (localStorage.getItem('sidebar_collapsed') === 'true') {
  collapsed.value = true
}

function isActive(item) {
  const path = route.path
  if (path === item.to) return true
  return path.startsWith(item.to + '/')
}

const ICON_DASHBOARD = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>`

const ICON_PROJECTS = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`

const ICON_SEARCH = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`

const ICON_PACK = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 3 7.5v9L12 21l9-4.5v-9L12 3Z"/><path d="m3 7.5 9 4.5 9-4.5"/><path d="M12 12v9"/></svg>`

const ICON_SETTINGS = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .4 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.4 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .4-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.4-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.4h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.4l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.4 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>`

const ICON_PRIVACY = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>`

const primaryNav = [
  { to: '/dashboard', label: 'Dashboard', icon: ICON_DASHBOARD },
  { to: '/projects', label: 'Projects', icon: ICON_PROJECTS },
  { to: '/search', label: 'Search', icon: ICON_SEARCH },
  { to: '/context-packs', label: 'Context Packs', icon: ICON_PACK }
]

const secondaryNav = [
  { to: '/settings', label: 'Settings', icon: ICON_SETTINGS },
  { to: '/privacy', label: 'Privacy', icon: ICON_PRIVACY }
]
</script>

<style scoped>
.sidebar {
  width: var(--layout-sidebar-w, 240px);
  flex-shrink: 0;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  padding: var(--space-5) var(--space-3);
  transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.sidebar--collapsed {
  width: 72px;
}

.sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-5);
  padding: 0 var(--space-2);
}

.sidebar--collapsed .sidebar__header {
  flex-direction: column;
  gap: var(--space-4);
  padding: 0;
}

.sidebar__brand {
  display: flex;
  align-items: center;
  min-width: 0;
  overflow: hidden;
}

.brand-logo-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.logo-img {
  height: 32px;
  width: auto;
  object-fit: contain;
}

.logo-img--1 {
  width: 32px;
}

.sidebar__toggle {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.sidebar__toggle:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
  border-color: var(--color-border);
}

.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar__nav--bottom {
  margin-top: auto;
}

.sidebar__section-title {
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--color-text-muted);
  padding: 0 var(--space-3);
  margin: var(--space-3) 0 var(--space-2);
  white-space: nowrap;
}

.sidebar__section-divider {
  height: 1px;
  background: var(--color-border);
  margin: var(--space-3) var(--space-2);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  transition: all 0.2s ease;
  text-decoration: none;
  white-space: nowrap;
}

.sidebar--collapsed .nav-item {
  justify-content: center;
  padding: 12px;
}

.nav-item:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.nav-item--active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.nav-item__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nav-item__label {
  font-weight: 500;
}

.sidebar__footer {
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
  margin-top: var(--space-3);
  display: flex;
  justify-content: center;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot--success {
  background: var(--color-success);
}
</style>
