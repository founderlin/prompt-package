<template>
  <aside class="sidebar">
    <div class="sidebar__brand">
      <img class="brand-logo" :src="logoSrc" alt="Prompt Package logo" />
      <span class="brand-name">Prompt Package</span>
    </div>

    <nav class="sidebar__nav" aria-label="Primary">
      <p class="sidebar__section-title">Workspace</p>
      <RouterLink
        v-for="item in primaryNav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item) }"
      >
        <span class="nav-item__icon" v-html="item.icon" aria-hidden="true" />
        <span class="nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <nav class="sidebar__nav sidebar__nav--bottom" aria-label="Secondary">
      <p class="sidebar__section-title">Account</p>
      <RouterLink
        v-for="item in secondaryNav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item) }"
      >
        <span class="nav-item__icon" v-html="item.icon" aria-hidden="true" />
        <span class="nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar__footer">
      <span class="chip">MVP · v0.1.0</span>
    </div>
  </aside>
</template>

<script setup>
import { RouterLink, useRoute } from 'vue-router'
import logoSrc from '@/icon.jpeg'

const route = useRoute()

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
  width: var(--layout-sidebar-w);
  flex-shrink: 0;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  padding: var(--space-5) var(--space-3);
}

.sidebar__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 0 var(--space-3);
  margin-bottom: var(--space-5);
}

.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  object-fit: cover;
  border: 1px solid var(--color-border);
}

.brand-name {
  font-size: var(--text-lg);
  font-weight: 500;
  letter-spacing: 0.2px;
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
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  transition: background-color 0.12s ease, color 0.12s ease;
  text-decoration: none;
}

.nav-item:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
  text-decoration: none;
}

.nav-item--active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.nav-item--active:hover {
  background: var(--color-primary-soft-hover);
  color: var(--color-primary);
}

.nav-item__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.nav-item__icon :deep(svg) {
  display: block;
}

.nav-item__label {
  font-weight: 500;
}

.sidebar__footer {
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
  margin-top: var(--space-3);
}
</style>
