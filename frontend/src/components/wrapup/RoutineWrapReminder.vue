<template>
  <transition name="reminder">
    <div
      v-if="visible"
      class="routine-reminder"
      role="status"
      aria-live="polite"
    >
      <div class="routine-reminder__body">
        <div class="routine-reminder__icon" aria-hidden="true">⏰</div>
        <div class="routine-reminder__text">
          <h4 class="routine-reminder__title">
            Routine Wrap is ready.
          </h4>
          <p class="routine-reminder__subtitle">
            Review {{ frequencyLabel }} project memory draft?
            <span v-if="config?.lastRunAt" class="routine-reminder__hint">
              Last wrapped {{ formatTime(config.lastRunAt) }}.
            </span>
          </p>
        </div>
      </div>
      <div class="routine-reminder__actions">
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          :disabled="busy"
          @click="onDismiss"
        >
          Dismiss
        </button>
        <button
          type="button"
          class="btn btn--primary btn--sm"
          :disabled="busy"
          @click="onReview"
        >
          Review
        </button>
      </div>
    </div>
  </transition>
</template>

<script setup>
/**
 * RoutineWrapReminder — Phase 5 reminder banner.
 *
 * Mounted inside the project chat view. The parent owns the
 * "should this be visible?" decision (driven by the
 * ``shouldPrompt`` field from ``GET /wraps/routine-status``); this
 * component is purely the visual + interaction.
 *
 * Props:
 *   visible : boolean — whether to render the banner
 *   config  : object  — routine config snapshot (for hint copy)
 *   busy    : boolean — disable buttons while parent is in-flight
 *
 * Events:
 *   review  — user clicked Review
 *   dismiss — user clicked Dismiss
 */
import { computed } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  config: { type: Object, default: null },
  busy: { type: Boolean, default: false }
})
const emit = defineEmits(['review', 'dismiss'])

const frequencyLabel = computed(() => {
  const f = props.config?.frequency
  if (f === 'weekly') return 'weekly'
  if (f === 'biweekly') return 'biweekly'
  if (f === 'monthly') return 'monthly'
  return 'routine'
})

function onReview() {
  emit('review')
}

function onDismiss() {
  emit('dismiss')
}

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  } catch (_err) {
    return iso
  }
}
</script>

<style scoped>
.routine-reminder {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 10px 14px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: var(--radius-md);
  margin: 0;
}

.routine-reminder__body {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}

.routine-reminder__icon {
  font-size: 22px;
  flex-shrink: 0;
}

.routine-reminder__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.routine-reminder__title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
}

.routine-reminder__subtitle {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.routine-reminder__hint {
  margin-left: 4px;
  font-style: italic;
}

.routine-reminder__actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.reminder-enter-active,
.reminder-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.reminder-enter-from,
.reminder-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
