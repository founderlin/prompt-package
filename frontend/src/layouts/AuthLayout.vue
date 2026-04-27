<template>
  <div class="auth-layout">
    <header class="auth-layout__brand">
      <RouterLink to="/" class="brand">
        <img class="brand-logo--full" :src="logoFull" alt="Prompt Package" />
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
import logoFull from '@/icon2.png'
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

.brand-logo--full {
  display: block;
  height: 40px;
  width: auto;
  object-fit: contain;
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
