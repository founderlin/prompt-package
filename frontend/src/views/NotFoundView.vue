<template>
  <div class="notfound">
    <EmptyState
      title="Page not found"
      :description="`We couldn’t find ${path}. The product is still being built — many routes are not wired yet.`"
    >
      <template #icon>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M9 9h.01M15 9h.01" />
          <path d="M8 16c1-1.5 2.5-2 4-2s3 .5 4 2" />
        </svg>
      </template>
      <template #actions>
        <RouterLink to="/dashboard" class="btn btn--primary">Back to Dashboard</RouterLink>
      </template>
    </EmptyState>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const path = computed(() => route.fullPath || '/')
</script>

<style scoped>
.notfound {
  padding-top: var(--space-5);
}
</style>
