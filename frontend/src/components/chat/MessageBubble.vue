<script setup>
import { computed } from 'vue'
import { modelLabel } from '@/constants/models'

const props = defineProps({
  message: { type: Object, required: true },
  highlighted: { type: Boolean, default: false }
})

const domId = computed(() => {
  // Only emit a stable DOM id when the message has a real (persisted) numeric id;
  // optimistic placeholders use ``_tempId`` and shouldn't be deep-linkable.
  if (props.message?.id == null) return undefined
  return `msg-${props.message.id}`
})

const isUser = computed(() => props.message.role === 'user')
const isAssistant = computed(() => props.message.role === 'assistant')
const isSystem = computed(() => props.message.role === 'system')

const avatarLabel = computed(() => {
  if (isUser.value) return 'You'
  if (isSystem.value) return 'Sys'
  return 'AI'
})

const meta = computed(() => {
  if (!isAssistant.value) return ''
  const parts = []
  if (props.message.model) parts.push(modelLabel(props.message.model))
  if (props.message.total_tokens != null) parts.push(`${props.message.total_tokens} tok`)
  return parts.join(' • ')
})

const time = computed(() => {
  if (!props.message.created_at) return ''
  try {
    return new Date(props.message.created_at).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch (_e) {
    return ''
  }
})
</script>

<template>
  <div
    :id="domId"
    class="bubble"
    :class="{
      'bubble--user': isUser,
      'bubble--assistant': isAssistant,
      'bubble--system': isSystem,
      'bubble--highlighted': highlighted
    }"
  >
    <div class="bubble__avatar" :class="{ 'bubble__avatar--user': isUser }">
      {{ avatarLabel }}
    </div>
    <div class="bubble__body">
      <div class="bubble__content">{{ message.content }}</div>
      <div v-if="meta || time" class="bubble__meta">
        <span v-if="meta" class="bubble__model">{{ meta }}</span>
        <span v-if="time" class="bubble__time">{{ time }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bubble {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}

.bubble--user {
  flex-direction: row-reverse;
}

.bubble__avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: var(--text-xs);
  letter-spacing: 0.02em;
}

.bubble__avatar--user {
  background: var(--color-primary);
  color: var(--color-text-on-primary);
}

.bubble__body {
  max-width: min(720px, 80%);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.bubble--user .bubble__body {
  align-items: flex-end;
}

.bubble__content {
  background: var(--color-surface);
  color: var(--color-text-primary);
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-1);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
  font-size: var(--text-base);
}

.bubble--user .bubble__content {
  background: var(--color-primary);
  color: var(--color-text-on-primary);
  border-color: transparent;
  border-bottom-right-radius: var(--radius-xs);
}

.bubble--assistant .bubble__content {
  border-bottom-left-radius: var(--radius-xs);
}

.bubble--system .bubble__content {
  background: var(--color-warning-soft);
  color: var(--color-warning);
  border-color: rgba(176, 96, 0, 0.3);
  font-style: italic;
}

.bubble__meta {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.bubble--user .bubble__meta {
  flex-direction: row-reverse;
}

.bubble__model {
  font-weight: 500;
}

.bubble--highlighted .bubble__content {
  animation: bubble-flash 1.6s ease-out;
  box-shadow: 0 0 0 3px rgba(255, 213, 79, 0.55);
}

@keyframes bubble-flash {
  0% {
    box-shadow: 0 0 0 0 rgba(255, 213, 79, 0.85);
  }
  20% {
    box-shadow: 0 0 0 6px rgba(255, 213, 79, 0.55);
  }
  100% {
    box-shadow: 0 0 0 3px rgba(255, 213, 79, 0);
  }
}
</style>
