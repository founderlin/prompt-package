<template>
  <!-- Fixed container anchored to the top-center of the viewport. Each
       toast is a banner-style row that slides down from -100% on enter
       and slides back up on leave. Because the container uses
       `pointer-events: none`, clicks on the surrounding page still go
       through; we re-enable pointer events on each toast card. -->
  <div class="toast-host" aria-live="polite" aria-atomic="true">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts.items"
        :key="t.id"
        :class="['toast', `toast--${t.kind}`]"
        role="status"
      >
        <span class="toast__message">{{ t.message }}</span>

        <RouterLink
          v-if="t.link && t.linkText"
          :to="t.link"
          class="toast__link"
          @click="toasts.dismiss(t.id)"
        >
          {{ t.linkText }}
        </RouterLink>

        <button
          type="button"
          class="toast__close"
          aria-label="Dismiss notification"
          @click="toasts.dismiss(t.id)"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { RouterLink } from 'vue-router'
import { useToasts } from '@/stores/toasts'

const toasts = useToasts()
</script>

<style scoped>
.toast-host {
  position: fixed;
  top: var(--space-3);
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  /* Let clicks pass through empty regions; re-enabled on each toast. */
  pointer-events: none;
  width: min(100%, 560px);
  padding: 0 var(--space-3);
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-3) 10px var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-3);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.toast--success {
  background: var(--color-primary-soft);
  border-color: rgba(26, 115, 232, 0.25);
  color: var(--color-text-primary);
}

.toast--error {
  background: var(--color-error-soft);
  border-color: rgba(220, 38, 38, 0.25);
  color: var(--color-error);
}

.toast--info {
  background: var(--color-surface);
}

.toast__message {
  flex: 1;
  min-width: 0;
  /* Allow long messages to wrap to 2 lines without pushing the close
     button off-screen. */
  line-height: 1.35;
}

.toast__link {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--color-primary);
  text-decoration: none;
  white-space: nowrap;
}

.toast__link:hover,
.toast__link:focus-visible {
  text-decoration: underline;
  text-underline-offset: 2px;
}

.toast__close {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.toast__close:hover,
.toast__close:focus-visible {
  background: rgba(15, 23, 42, 0.06);
  color: var(--color-text-primary);
}

/* ---- Slide-in / slide-out transitions (top → down / up → gone) ---- */
.toast-enter-active,
.toast-leave-active {
  transition:
    transform 0.28s cubic-bezier(0.2, 0.8, 0.2, 1),
    opacity 0.22s ease;
}

.toast-enter-from {
  transform: translateY(-140%);
  opacity: 0;
}

.toast-enter-to {
  transform: translateY(0);
  opacity: 1;
}

.toast-leave-from {
  transform: translateY(0);
  opacity: 1;
}

.toast-leave-to {
  transform: translateY(-140%);
  opacity: 0;
}

/* Keep stacked toasts shifting neatly when one above is removed. */
.toast-move {
  transition: transform 0.25s ease;
}
</style>
