<template>
  <Teleport to="body">
    <transition name="dialog">
      <div
        v-if="open"
        class="dialog-backdrop"
        role="presentation"
        @mousedown.self="onBackdrop"
      >
        <div
          class="dialog"
          role="alertdialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :aria-describedby="descriptionId"
        >
          <header class="dialog__header">
            <h2 :id="titleId" class="dialog__title">{{ title }}</h2>
          </header>

          <div class="dialog__body">
            <p :id="descriptionId" class="dialog__message">
              <slot>{{ message }}</slot>
            </p>
          </div>

          <footer class="dialog__actions">
            <button
              ref="cancelBtn"
              type="button"
              class="btn btn--ghost"
              :disabled="busy"
              @click="onCancel"
            >
              {{ cancelLabel }}
            </button>
            <button
              type="button"
              class="btn"
              :class="[tone === 'danger' ? 'btn--danger' : 'btn--primary']"
              :disabled="busy"
              @click="onConfirm"
            >
              <span v-if="busy" class="spinner" aria-hidden="true" />
              {{ busy ? busyLabel : confirmLabel }}
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * Minimal modal confirm dialog.
 *
 * Replaces the native ``window.confirm()`` calls used elsewhere in the
 * codebase for destructive actions. Styled to match the rest of the
 * app's dialog surface (ProjectFormDialog, WrapUpDialog).
 *
 * Props:
 *   open          — v-model-able boolean driving visibility
 *   title         — header text
 *   message       — body text; a default slot overrides it when needed
 *   confirmLabel  — primary button copy (default "Confirm")
 *   cancelLabel   — secondary button copy (default "Cancel")
 *   busyLabel     — copy shown on the primary while ``busy`` is true
 *   tone          — 'danger' | 'primary' (default 'primary'). Controls
 *                   the primary button color.
 *   busy          — while true, disables buttons and shows a spinner.
 *                   The parent usually sets this during the async call.
 *
 * Emits:
 *   confirm       — user clicked the primary button. Parent is
 *                   responsible for setting ``busy`` while the action
 *                   runs, and for flipping ``open`` to false on finish.
 *   cancel        — user dismissed (cancel button / backdrop / Escape).
 *   update:open   — when the backdrop/Escape/cancel dismisses the
 *                   dialog, we also emit this so callers can use
 *                   ``v-model:open``.
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch
} from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: 'Are you sure?' },
  message: { type: String, default: '' },
  confirmLabel: { type: String, default: 'Confirm' },
  cancelLabel: { type: String, default: 'Cancel' },
  busyLabel: { type: String, default: 'Working…' },
  tone: {
    type: String,
    default: 'primary',
    validator: (v) => v === 'primary' || v === 'danger'
  },
  busy: { type: Boolean, default: false }
})

const emit = defineEmits(['confirm', 'cancel', 'update:open'])

const uid = Math.random().toString(36).slice(2, 8)
const titleId = `confirm-dialog-title-${uid}`
const descriptionId = `confirm-dialog-desc-${uid}`
const cancelBtn = ref(null)

watch(
  () => props.open,
  async (next) => {
    if (next) {
      await nextTick()
      // Focus the safe (cancel) action by default; matches common
      // confirm-dialog UX where the destructive path is never the
      // default-focused element.
      cancelBtn.value?.focus()
      window.addEventListener('keydown', onKeydown)
    } else {
      window.removeEventListener('keydown', onKeydown)
    }
  }
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

function onKeydown(e) {
  if (e.key === 'Escape' && !props.busy) {
    emitCancel()
  }
}

function onBackdrop() {
  if (props.busy) return
  emitCancel()
}

function onCancel() {
  if (props.busy) return
  emitCancel()
}

function onConfirm() {
  if (props.busy) return
  emit('confirm')
}

function emitCancel() {
  emit('cancel')
  emit('update:open', false)
}
</script>

<style scoped>
/* Shares the look of ProjectFormDialog / WrapUpDialog so the app
   never shows two different modal styles. If we ever extract a shared
   Dialog primitive, this component will be one of three consumers and
   the CSS can move there. */

.dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-4);
}

.dialog {
  background: var(--color-surface);
  width: min(440px, 100%);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-3, 0 20px 50px rgba(0, 0, 0, 0.18));
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog__header {
  padding: var(--space-4) var(--space-5) 0;
}

.dialog__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 500;
  color: var(--color-text-primary);
}

.dialog__body {
  padding: var(--space-3) var(--space-5) var(--space-5);
}

.dialog__message {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.dialog__actions {
  padding: var(--space-3) var(--space-5) var(--space-4);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.15s ease;
}
.dialog-enter-active .dialog,
.dialog-leave-active .dialog {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
.dialog-enter-from .dialog,
.dialog-leave-to .dialog {
  transform: translateY(8px) scale(0.98);
  opacity: 0;
}
</style>
