<template>
  <div class="shell">
    <SidebarNav />
    <div class="shell__main">
      <main class="shell__content">
        <RouterView />
      </main>
    </div>
    <!-- Global top-center toast stack. Mounted once at the shell level so
         any authenticated route can call `useToasts().push(...)` without
         each view needing its own host. -->
    <ToastHost />
  </div>
</template>

<script setup>
import { RouterView } from 'vue-router'
import SidebarNav from '@/components/layout/SidebarNav.vue'
import ToastHost from '@/components/common/ToastHost.vue'
// AppHeader was removed — the account area now lives at the bottom of the
// sidebar (see SidebarNav.vue). Removing the 64px top bar gives the chat
// view and every other page that much more vertical breathing room.
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
