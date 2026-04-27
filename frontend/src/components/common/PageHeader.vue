<template>
  <header class="page-header">
    <div class="page-header__text">
      <h2 class="page-header__title">{{ title }}</h2>
      <p v-if="description" class="page-header__description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' }
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}

.page-header__text {
  min-width: 0;
}

.page-header__title {
  font-size: var(--text-2xl);
  font-weight: 500;
  margin: 0 0 var(--space-1);
  letter-spacing: 0.1px;
}

.page-header__description {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  margin: 0;
  max-width: 720px;
}

.page-header__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
