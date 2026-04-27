<template>
  <div class="shell">
    <SidebarNav />
    <div class="shell__main">
      <AppHeader />
      <main class="shell__content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup>
import { RouterView } from 'vue-router'
import SidebarNav from '@/components/layout/SidebarNav.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
</script>

<style scoped>
.shell {
  display: flex;
  align-items: stretch;
  min-height: 100vh;
  background: var(--color-bg);
}

.shell__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.shell__content {
  flex: 1;
  width: 100%;
  max-width: var(--layout-content-max);
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-7);
}

@media (max-width: 720px) {
  .shell__content {
    padding: var(--space-5) var(--space-4) var(--space-6);
  }
}
</style>
