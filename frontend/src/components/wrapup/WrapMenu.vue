<template>
  <div ref="rootEl" class="wrap-menu">
    <button
      ref="triggerEl"
      type="button"
      class="btn btn--ghost btn--sm wrap-menu__trigger"
      :class="{ 'wrap-menu__trigger--open': isOpen }"
      :disabled="disabled"
      :title="disabled ? disabledTitle : 'Wrap this session into project memory'"
      :aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="toggle"
    >
      <span>Wrap</span>
      <svg
        class="wrap-menu__caret"
        :class="{ 'wrap-menu__caret--open': isOpen }"
        width="10"
        height="10"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <ul
      v-if="isOpen"
      class="wrap-menu__panel"
      role="menu"
    >
      <li role="presentation">
        <button
          type="button"
          role="menuitem"
          class="wrap-menu__item"
          @click="select('quick')"
        >
          <span class="wrap-menu__item-title">Quick Wrap</span>
          <span class="wrap-menu__item-hint">
            One-click · default model + filters
          </span>
        </button>
      </li>
      <li role="presentation">
        <button
          type="button"
          role="menuitem"
          class="wrap-menu__item"
          @click="select('advanced')"
        >
          <span class="wrap-menu__item-title">Advanced Wrap</span>
          <span class="wrap-menu__item-hint">
            Choose model, edit filters, review Markdown
          </span>
        </button>
      </li>
      <li role="presentation">
        <button
          type="button"
          role="menuitem"
          class="wrap-menu__item"
          @click="select('routine-settings')"
        >
          <span class="wrap-menu__item-title">Routine Wrap Settings</span>
          <span class="wrap-menu__item-hint">
            Schedule periodic wraps; default weekly
          </span>
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
/**
 * WrapMenu — a small dropdown trigger that exposes the three Wrap
 * entry points:
 *
 *   - Quick Wrap            (enabled, Phase 3)
 *   - Advanced Wrap         (enabled, Phase 4)
 *   - Routine Wrap Settings (enabled, Phase 5)
 *
 * Emits ``select('quick' | 'advanced' | 'routine-settings')`` when
 * the user picks an item. The parent owns the actual flow (mounting
 * the right dialog, showing toasts, etc.) — this component is purely
 * the entry-point widget.
 *
 * Lightweight on purpose: no positioning library, no transitions.
 * Closes on outside click, Escape, or after selecting an item.
 */
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  disabledTitle: {
    type: String,
    default: 'Send at least one user/assistant exchange first'
  }
})

const emit = defineEmits(['select'])

const isOpen = ref(false)
const rootEl = ref(null)
const triggerEl = ref(null)

function toggle() {
  if (props.disabled) return
  isOpen.value = !isOpen.value
}

function close() {
  isOpen.value = false
}

function select(kind) {
  close()
  emit('select', kind)
}

function onDocumentClick(e) {
  if (!isOpen.value) return
  const root = rootEl.value
  if (root && !root.contains(e.target)) {
    close()
  }
}

function onKeydown(e) {
  if (e.key === 'Escape' && isOpen.value) {
    close()
    triggerEl.value?.focus()
  }
}

watch(isOpen, (next) => {
  if (next) {
    document.addEventListener('mousedown', onDocumentClick)
    document.addEventListener('keydown', onKeydown)
  } else {
    document.removeEventListener('mousedown', onDocumentClick)
    document.removeEventListener('keydown', onKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.wrap-menu {
  position: relative;
  display: inline-block;
}

.wrap-menu__trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.wrap-menu__caret {
  transition: transform 0.15s ease;
}

.wrap-menu__caret--open {
  transform: rotate(180deg);
}

.wrap-menu__panel {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 260px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-2, 0 8px 24px rgba(0, 0, 0, 0.12));
  list-style: none;
  margin: 0;
  padding: 4px;
  z-index: 100;
}

.wrap-menu__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-text-primary);
}

.wrap-menu__item:hover:not(:disabled),
.wrap-menu__item:focus-visible {
  background: var(--color-surface-muted);
  outline: none;
}

.wrap-menu__item--disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.wrap-menu__item-title {
  font-size: var(--text-sm);
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.wrap-menu__item-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.wrap-menu__badge {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-muted);
  font-weight: 600;
}
</style>
