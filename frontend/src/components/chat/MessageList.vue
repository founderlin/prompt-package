<script setup>
import { nextTick, ref, watch } from 'vue'
import MessageBubble from './MessageBubble.vue'

const props = defineProps({
  messages: { type: Array, required: true },
  pending: { type: Boolean, default: false },
  highlightId: { type: [Number, String, null], default: null }
})

const scrollEl = ref(null)

async function scrollToBottom() {
  await nextTick()
  const el = scrollEl.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => [props.messages.length, props.pending],
  scrollToBottom,
  { immediate: true }
)
</script>

<template>
  <div ref="scrollEl" class="message-list">
    <div v-if="!messages.length && !pending" class="message-list__empty">
      <p class="message-list__empty-title">Start the conversation</p>
      <p class="message-list__empty-hint">
        Ask the model anything about this project. Conversations are saved automatically.
      </p>
    </div>

    <div v-else class="message-list__feed">
      <MessageBubble
        v-for="msg in messages"
        :key="msg.id || msg._tempId"
        :message="msg"
        :highlighted="
          highlightId != null && msg.id != null && Number(msg.id) === Number(highlightId)
        "
      />
      <div v-if="pending" class="message-list__pending" aria-live="polite">
        <span class="dot" />
        <span class="dot" />
        <span class="dot" />
        <span class="message-list__pending-label">Model is thinking…</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5) var(--space-5);
  background: var(--color-bg);
}

.message-list__feed {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-width: 920px;
  margin: 0 auto;
}

.message-list__empty {
  max-width: 480px;
  margin: var(--space-7) auto;
  text-align: center;
  color: var(--color-text-secondary);
}

.message-list__empty-title {
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--color-text-primary);
  margin: 0 0 var(--space-2);
}

.message-list__empty-hint {
  margin: 0;
  font-size: var(--text-base);
  line-height: 1.55;
}

.message-list__pending {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  width: fit-content;
  margin-left: 44px;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
  display: inline-block;
  animation: bubble-bounce 1.2s infinite ease-in-out;
}

.dot:nth-child(2) { animation-delay: 0.15s; }
.dot:nth-child(3) { animation-delay: 0.3s; }

.message-list__pending-label {
  margin-left: 6px;
}

@keyframes bubble-bounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.45;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
