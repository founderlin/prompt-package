<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': collapsed }">
    <!-- Brand: icon2 (full horizontal logo) when expanded, icon1 (mark) when collapsed. -->
    <div class="sidebar__brand">
      <RouterLink to="/" class="brand-link" :aria-label="collapsed ? 'Prompt Package' : undefined">
        <img
          v-if="collapsed"
          class="brand-logo--mark"
          :src="logoMark"
          alt="Prompt Package"
        />
        <img
          v-else
          class="brand-logo--full"
          :src="logoFull"
          alt="Prompt Package"
        />
      </RouterLink>
    </div>

    <nav class="sidebar__nav" aria-label="Primary">
      <p v-show="!collapsed" class="sidebar__section-title">Workspace</p>
      <RouterLink
        v-for="item in primaryNav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item) }"
        :title="collapsed ? item.label : undefined"
      >
        <span class="nav-item__icon" v-html="item.icon" aria-hidden="true" />
        <span class="nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <nav class="sidebar__nav sidebar__nav--bottom" aria-label="Secondary">
      <p v-show="!collapsed" class="sidebar__section-title">Account</p>
      <RouterLink
        v-for="item in secondaryNav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item) }"
        :title="collapsed ? item.label : undefined"
      >
        <span class="nav-item__icon" v-html="item.icon" aria-hidden="true" />
        <span class="nav-item__label">{{ item.label }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar__footer">
      <span v-show="!collapsed" class="chip">MVP · v0.1.0</span>
    </div>

    <!-- Collapse / expand toggle. Sits on the right edge of the sidebar so
         it visually "pokes out" and reads as the affordance that moves the
         sidebar in and out, regardless of its current state. -->
    <button
      type="button"
      class="sidebar__toggle"
      :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
      :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
      :aria-expanded="!collapsed"
      @click="toggle"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.4"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <polyline v-if="collapsed" points="9 6 15 12 9 18" />
        <polyline v-else points="15 6 9 12 15 18" />
      </svg>
    </button>
  </aside>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import logoFull from '@/icon2.png'
import logoMark from '@/icon1.png'

const route = useRoute()

const STORAGE_KEY = 'pp_sidebar_collapsed'
const collapsed = ref(false)

onMounted(() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === '1') collapsed.value = true
  } catch (_e) {
    /* ignore storage errors */
  }
  // Always publish the current width so panes that size against the
  // variable (e.g. the chat shell) pick up the right value on first paint.
  document.documentElement.style.setProperty(
    '--layout-sidebar-w',
    collapsed.value ? '72px' : '240px'
  )
})

watch(collapsed, (next) => {
  try {
    localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
  } catch (_e) {
    /* ignore storage errors */
  }
  // Sync a CSS variable so other parts of the app (e.g. sticky chat
  // layout sizing) can react without prop drilling.
  document.documentElement.style.setProperty(
    '--layout-sidebar-w',
    next ? '72px' : '240px'
  )
})

function toggle() {
  collapsed.value = !collapsed.value
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
  /* Sidebar owns its own width so we can animate it smoothly without
     depending on the outer layout; --layout-sidebar-w is still synced
     from the component so other panes (e.g. chat shell) can read it. */
  width: 240px;
  flex-shrink: 0;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  padding: var(--space-5) var(--space-3);
  transition: width 0.22s ease, padding 0.22s ease;
  z-index: 10;
}

.sidebar--collapsed {
  width: 72px;
  padding-left: 0;
  padding-right: 0;
}

/* ---- Brand ---- */
.sidebar__brand {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 var(--space-3);
  margin-bottom: var(--space-5);
  min-height: 40px;
}

.sidebar--collapsed .sidebar__brand {
  padding: 0;
}

.brand-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  width: 100%;
}

.brand-link:hover {
  text-decoration: none;
}

/* Full horizontal logo (icon2) — expanded state. Scaled to fit the
   sidebar width while keeping its native aspect ratio. */
.brand-logo--full {
  display: block;
  width: 100%;
  max-width: 200px;
  height: auto;
  object-fit: contain;
}

/* Compact square mark (icon1) — collapsed state. */
.brand-logo--mark {
  display: block;
  width: 40px;
  height: 40px;
  object-fit: contain;
}

/* ---- Nav sections ---- */
.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--space-3);
}

.sidebar--collapsed .sidebar__nav {
  padding: 0 var(--space-2);
  align-items: stretch;
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
  /* Clip label crossfade inside the bounds of the item. */
  overflow: hidden;
  white-space: nowrap;
}

.sidebar--collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
  gap: 0;
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
  flex-shrink: 0;
}

.nav-item__icon :deep(svg) {
  display: block;
}

.nav-item__label {
  font-weight: 500;
  opacity: 1;
  transition: opacity 0.15s ease;
}

.sidebar--collapsed .nav-item__label {
  opacity: 0;
  width: 0;
  pointer-events: none;
}

/* ---- Footer ---- */
.sidebar__footer {
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
  margin-top: var(--space-3);
  min-height: 32px;
}

.sidebar--collapsed .sidebar__footer {
  padding: var(--space-2);
  border-top: 1px solid var(--color-border);
}

/* ---- Collapse toggle ---- */
.sidebar__toggle {
  position: absolute;
  top: 24px;
  right: -13px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
  transition: background-color 0.12s ease, color 0.12s ease,
    border-color 0.12s ease, transform 0.12s ease;
  z-index: 11;
}

.sidebar__toggle:hover {
  background: var(--color-primary);
  color: var(--color-text-on-primary);
  border-color: var(--color-primary);
  transform: scale(1.05);
}

.sidebar__toggle:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
</style>
