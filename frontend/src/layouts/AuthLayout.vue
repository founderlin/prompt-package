<template>
  <div class="auth-layout">
    <header class="auth-layout__brand">
      <RouterLink to="/" class="brand">
        <img class="brand-logo" :src="logoSrc" alt="Prompt Package logo" />
        <span class="brand-name">Prompt Package</span>
      </RouterLink>
    </header>

    <main class="auth-layout__main">
      <slot />
    </main>

    <footer class="auth-layout__footer">
      <span>Prompt Package · MVP v0.1.0</span>
      <span>·</span>
      <RouterLink to="/privacy">Privacy</RouterLink>
    </footer>
  </div>
</template>

<script setup>
import { RouterLink } from 'vue-router'
import logoSrc from '@/icon.jpeg'
</script>

<style scoped>
.auth-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
}

.auth-layout__brand {
  display: flex;
  align-items: center;
  padding: var(--space-5) var(--space-6);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-primary);
  text-decoration: none;
}

.brand:hover {
  text-decoration: none;
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
}

.auth-layout__main {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
}

.auth-layout__footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-5);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
