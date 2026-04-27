<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  pending: { type: Boolean, default: false },
  placeholder: {
    type: String,
    default: 'Type your message… (Enter to send, Shift+Enter for newline)'
  }
})

const emit = defineEmits(['update:modelValue', 'submit'])

const textareaRef = ref(null)
const internal = ref(props.modelValue || '')

watch(
  () => props.modelValue,
  (next) => {
    if (next !== internal.value) internal.value = next || ''
  }
)

function autoresize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 220)}px`
}

watch(internal, (next) => {
  emit('update:modelValue', next)
  nextTick(autoresize)
})

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

function submit() {
  if (props.disabled || props.pending) return
  const trimmed = internal.value.trim()
  if (!trimmed) return
  emit('submit', trimmed)
}

const canSend = computed(
  () => !props.disabled && !props.pending && internal.value.trim().length > 0
)

defineExpose({
  focus: () => {
    nextTick(() => textareaRef.value?.focus())
  },
  reset: () => {
    internal.value = ''
    nextTick(autoresize)
  }
})
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <textarea
      ref="textareaRef"
      v-model="internal"
      class="composer__textarea"
      rows="1"
      :placeholder="placeholder"
      :disabled="disabled"
      @keydown="handleKeydown"
    />
    <div class="composer__actions">
      <div class="composer__actions-left">
        <slot name="leading" />
      </div>
      <div class="composer__actions-right">
        <span class="composer__hint">Enter to send · Shift+Enter for newline</span>
        <button
          type="submit"
          class="btn btn--primary composer__submit"
          :disabled="!canSend"
        >
          <span v-if="pending" class="spinner" aria-hidden="true" />
          <span>{{ pending ? 'Sending…' : 'Send' }}</span>
        </button>
      </div>
    </div>
  </form>
</template>

<style scoped>
.composer {
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: var(--space-3) var(--space-5) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.composer__textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  font-family: inherit;
  font-size: var(--text-base);
  line-height: 1.55;
  background: var(--color-surface);
  color: var(--color-text-primary);
  min-height: 44px;
  max-height: 220px;
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}

.composer__textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.composer__textarea:disabled {
  background: var(--color-surface-muted);
  cursor: not-allowed;
}

.composer__actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.composer__actions-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  flex: 1;
}

.composer__actions-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}

.composer__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.composer__submit {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.composer__submit .spinner {
  border-color: rgba(255, 255, 255, 0.4);
  border-top-color: var(--color-text-on-primary);
}
</style>
