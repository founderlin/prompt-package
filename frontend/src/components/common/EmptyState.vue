<template>
  <div class="empty-state" :class="{ 'empty-state--compact': compact }">
    <div class="empty-state__icon" aria-hidden="true">
      <slot name="icon">
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
          <path d="M9 10h.01M15 10h.01" />
          <path d="M9 15c.83.6 1.86 1 3 1s2.17-.4 3-1" />
        </svg>
      </slot>
    </div>

    <h3 class="empty-state__title">{{ title }}</h3>
    <p v-if="description" class="empty-state__description">{{ description }}</p>

    <div v-if="$slots.actions" class="empty-state__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  compact: { type: Boolean, default: false }
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-7) var(--space-5);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.empty-state--compact {
  padding: var(--space-5) var(--space-4);
}

.empty-state__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  margin-bottom: var(--space-4);
}

.empty-state--compact .empty-state__icon {
  width: 44px;
  height: 44px;
}

.empty-state__icon :deep(svg) {
  display: block;
}

.empty-state__title {
  font-size: var(--text-md);
  font-weight: 500;
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
}

.empty-state__description {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  max-width: 420px;
  margin: 0 0 var(--space-4);
}

.empty-state__actions {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  justify-content: center;
}
</style>
