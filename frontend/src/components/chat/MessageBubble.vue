<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import apiClient from '@/api/client'
import attachmentsApi from '@/api/attachments'
import { modelLabel } from '@/constants/models'

const props = defineProps({
  message: { type: Object, required: true },
  highlighted: { type: Boolean, default: false }
})

const domId = computed(() => {
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
  if (props.message.total_tokens != null)
    parts.push(`${props.message.total_tokens} tok`)
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

const attachments = computed(() => {
  const list = Array.isArray(props.message.attachments)
    ? props.message.attachments
    : []
  return list
})

// Native <img src> can't send an Authorization header, so for image
// attachments we fetch them as blobs through the authenticated axios
// client, create an object URL, and render that. Each message bubble
// keeps its own cache keyed by attachment id so we don't re-fetch on
// every re-render. Object URLs are revoked on unmount.
const imageUrls = ref({})

function cacheKey(att) {
  return `a-${att.id || att.clientId || ''}`
}

async function loadImageFor(att) {
  if (!att) return
  const key = cacheKey(att)
  if (imageUrls.value[key]) return
  // Optimistic upload still has a previewUrl — prefer that locally.
  if (att.previewUrl) {
    imageUrls.value[key] = att.previewUrl
    return
  }
  if (!att.id || !props.message.conversation_id) return
  try {
    const res = await apiClient.get(
      `/api/conversations/${props.message.conversation_id}/attachments/${att.id}/download`,
      { responseType: 'blob' }
    )
    const blob = res.data
    if (typeof URL?.createObjectURL === 'function') {
      imageUrls.value[key] = URL.createObjectURL(blob)
    }
  } catch (_err) {
    // Mark as failed so we stop retrying.
    imageUrls.value[key] = ''
  }
}

function loadAllImages() {
  for (const att of attachments.value) {
    if (att.kind === 'image') loadImageFor(att)
  }
}

watch(
  () => attachments.value,
  () => loadAllImages(),
  { immediate: true, deep: true }
)

onBeforeUnmount(() => {
  for (const url of Object.values(imageUrls.value)) {
    if (!url) continue
    // Don't revoke the `previewUrl` one — the parent view owns it.
    if (typeof URL?.revokeObjectURL === 'function') {
      try {
        URL.revokeObjectURL(url)
      } catch (_e) {
        /* ignore */
      }
    }
  }
})

function downloadUrl(att) {
  if (!props.message.conversation_id || !att?.id) return '#'
  return attachmentsApi.downloadUrl(props.message.conversation_id, att.id)
}

function formatBytes(n) {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

async function onFileClick(att, event) {
  // Native anchor download doesn't send our auth header, so fetch as
  // blob and trigger a download programmatically.
  if (!att?.id || !props.message.conversation_id) return
  event.preventDefault()
  try {
    const res = await apiClient.get(
      `/api/conversations/${props.message.conversation_id}/attachments/${att.id}/download`,
      { responseType: 'blob' }
    )
    const blob = res.data
    if (typeof URL?.createObjectURL === 'function') {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = att.filename || 'attachment'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
  } catch (_err) {
    /* no-op */
  }
}
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
      <div
        v-if="message.content"
        class="bubble__content"
      >{{ message.content }}</div>

      <ul
        v-if="attachments.length"
        class="bubble__attachments"
        :class="{ 'bubble__attachments--user': isUser }"
        aria-label="Attached files"
      >
        <li
          v-for="att in attachments"
          :key="att.id || att.clientId"
          class="bubble-attachment"
          :class="{
            'bubble-attachment--image': att.kind === 'image'
          }"
        >
          <a
            v-if="att.kind === 'image'"
            :href="downloadUrl(att)"
            @click="onFileClick(att, $event)"
            class="bubble-attachment__image-link"
            :title="att.filename"
          >
            <img
              v-if="imageUrls[cacheKey(att)]"
              :src="imageUrls[cacheKey(att)]"
              :alt="att.filename"
              class="bubble-attachment__image"
            />
            <span v-else class="bubble-attachment__image-fallback">
              <span class="spinner" aria-hidden="true" />
            </span>
          </a>
          <a
            v-else
            :href="downloadUrl(att)"
            class="bubble-attachment__file"
            @click="onFileClick(att, $event)"
          >
            <span
              class="bubble-attachment__icon"
              :data-kind="(att.kind || 'file').toLowerCase()"
              aria-hidden="true"
            >
              <svg
                v-if="att.kind === 'pdf'"
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <text x="8" y="17" font-size="6" font-weight="700" fill="currentColor" stroke="none">PDF</text>
              </svg>
              <svg
                v-else
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="8" y1="13" x2="16" y2="13" />
                <line x1="8" y1="17" x2="14" y2="17" />
              </svg>
            </span>
            <span class="bubble-attachment__meta">
              <span class="bubble-attachment__name">{{ att.filename }}</span>
              <span class="bubble-attachment__sub">
                {{ formatBytes(att.size_bytes) }}
                <template v-if="att.kind === 'pdf'"> · PDF</template>
                <template v-else-if="att.kind === 'text'"> · Text</template>
                <template v-if="att.text_truncated"> · truncated</template>
              </span>
            </span>
          </a>
        </li>
      </ul>

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

/* ---- Attachment rendering ---- */
.bubble__attachments {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-width: 100%;
}

.bubble__attachments--user {
  justify-content: flex-end;
}

.bubble-attachment {
  display: flex;
  align-items: center;
}

.bubble-attachment--image {
  max-width: 260px;
}

.bubble-attachment__image-link {
  display: block;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  line-height: 0;
  transition: border-color 0.12s ease, transform 0.12s ease;
}

.bubble-attachment__image-link:hover {
  border-color: var(--color-border-strong);
  transform: translateY(-1px);
}

.bubble-attachment__image {
  display: block;
  max-width: 260px;
  max-height: 260px;
  width: auto;
  height: auto;
}

.bubble-attachment__image-fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 200px;
  height: 140px;
}

.bubble-attachment__file {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-1);
  text-decoration: none;
  color: inherit;
  transition: background-color 0.12s ease, border-color 0.12s ease,
    transform 0.12s ease;
  max-width: 300px;
}

.bubble-attachment__file:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
  transform: translateY(-1px);
}

.bubble-attachment__icon {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
}

.bubble-attachment__icon[data-kind='pdf'] {
  background: rgba(198, 40, 40, 0.08);
  color: #c62828;
}

.bubble-attachment__icon[data-kind='text'] {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.bubble-attachment__meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 220px;
}

.bubble-attachment__name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bubble-attachment__sub {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* On user bubbles, attachments sit right-aligned. The file-chip variant
   uses the same styling either way so it reads the same in both columns. */
</style>
