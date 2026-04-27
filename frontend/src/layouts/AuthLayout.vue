<template>
  <div class="auth-layout">
    <header class="auth-layout__brand">
      <RouterLink to="/" class="brand">
        <div class="brand-logo-wrap">
          <img :src="logo1" alt="Logo part 1" class="logo-img" />
          <img :src="logo2" alt="Logo part 2" class="logo-img" />
        </div>
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
import logo1 from '@/assets/logo1.png'
import logo2 from '@/assets/logo2.png'
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
  text-decoration: none;
}

.brand-logo-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-img {
  height: 32px;
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
