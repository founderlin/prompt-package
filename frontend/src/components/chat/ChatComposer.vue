<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  pending: { type: Boolean, default: false },
  placeholder: {
    type: String,
    default: 'Type your message… (Enter to send, Shift+Enter for newline)'
  },
  /** Uploaded/uploading attachment objects. See ProjectChatView for shape. */
  attachments: { type: Array, default: () => [] },
  /** Comma-separated list of MIME types the file input accepts. */
  accept: {
    type: String,
    default:
      'image/png,image/jpeg,image/jpg,image/webp,image/gif,application/pdf,text/plain,text/markdown,.md,.txt'
  },
  maxAttachments: { type: Number, default: 8 }
})

const emit = defineEmits([
  'update:modelValue',
  'submit',
  'add-files',
  'remove-attachment'
])

const textareaRef = ref(null)
const fileInputRef = ref(null)
const shellRef = ref(null)
const internal = ref(props.modelValue || '')
const isDragging = ref(false)
let dragCounter = 0

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
  if (anyUploading.value) return
  const trimmed = internal.value.trim()
  if (!trimmed && props.attachments.length === 0) return
  emit('submit', trimmed)
}

const anyUploading = computed(() =>
  (props.attachments || []).some((a) => a.status === 'uploading')
)

const canSend = computed(
  () =>
    !props.disabled &&
    !props.pending &&
    !anyUploading.value &&
    (internal.value.trim().length > 0 || props.attachments.length > 0)
)

const atLimit = computed(
  () => (props.attachments?.length || 0) >= props.maxAttachments
)

function openFilePicker() {
  if (props.disabled || props.pending || atLimit.value) return
  fileInputRef.value?.click()
}

function onFileInputChange(event) {
  const files = Array.from(event.target?.files || [])
  if (files.length) {
    emit('add-files', files)
  }
  // Reset so re-selecting the same file still fires change.
  if (event.target) event.target.value = ''
}

function onPaste(event) {
  const items = event.clipboardData?.items
  if (!items) return
  const files = []
  for (const item of items) {
    if (item.kind === 'file') {
      const f = item.getAsFile()
      if (f) files.push(f)
    }
  }
  if (files.length) {
    event.preventDefault()
    emit('add-files', files)
  }
}

// ---- Drag & drop on the whole composer shell ----
function onDragEnter(event) {
  if (props.disabled) return
  const types = event.dataTransfer?.types
  if (!types || !Array.prototype.includes.call(types, 'Files')) return
  dragCounter += 1
  isDragging.value = true
}

function onDragOver(event) {
  if (props.disabled) return
  const types = event.dataTransfer?.types
  if (!types || !Array.prototype.includes.call(types, 'Files')) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(event) {
  if (props.disabled) return
  dragCounter = Math.max(0, dragCounter - 1)
  if (dragCounter === 0) {
    isDragging.value = false
  }
}

function onDrop(event) {
  if (props.disabled) return
  dragCounter = 0
  isDragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length) {
    event.preventDefault()
    emit('add-files', files)
  }
}

defineExpose({
  focus: () => {
    nextTick(() => textareaRef.value?.focus())
  },
  reset: () => {
    internal.value = ''
    nextTick(autoresize)
  }
})

function formatBytes(n) {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function iconForAttachment(att) {
  return (att.kind || 'file').toLowerCase()
}
</script>

<template>
  <form
    class="composer"
    :class="{ 'composer--dragging': isDragging }"
    ref="shellRef"
    @submit.prevent="submit"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <!-- Attachment thumbnails row (above the textarea). -->
    <ul
      v-if="attachments.length"
      class="composer__attachments"
      aria-label="Attached files"
    >
      <li
        v-for="att in attachments"
        :key="att.clientId || att.id"
        class="attachment-chip"
        :class="{
          'attachment-chip--uploading': att.status === 'uploading',
          'attachment-chip--error': att.status === 'error'
        }"
      >
        <div class="attachment-chip__thumb">
          <img
            v-if="att.kind === 'image' && att.previewUrl"
            :src="att.previewUrl"
            :alt="att.filename"
          />
          <span
            v-else
            class="attachment-chip__icon"
            :data-kind="iconForAttachment(att)"
            aria-hidden="true"
          >
            <svg
              v-if="att.kind === 'pdf'"
              width="18"
              height="18"
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
              width="18"
              height="18"
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
          <div
            v-if="att.status === 'uploading'"
            class="attachment-chip__progress"
          >
            <div
              class="attachment-chip__progress-bar"
              :style="{ width: `${Math.round((att.progress || 0) * 100)}%` }"
            />
          </div>
        </div>
        <div class="attachment-chip__meta">
          <span class="attachment-chip__name" :title="att.filename">
            {{ att.filename }}
          </span>
          <span class="attachment-chip__sub">
            <template v-if="att.status === 'uploading'">
              Uploading… {{ Math.round((att.progress || 0) * 100) }}%
            </template>
            <template v-else-if="att.status === 'error'">
              {{ att.error || 'Upload failed' }}
            </template>
            <template v-else>
              {{ formatBytes(att.size_bytes || att.size || 0) }}
            </template>
          </span>
        </div>
        <button
          type="button"
          class="attachment-chip__remove"
          :title="att.status === 'uploading' ? 'Cancel upload' : 'Remove'"
          :aria-label="`Remove ${att.filename}`"
          @click="emit('remove-attachment', att)"
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <line x1="6" y1="6" x2="18" y2="18" />
            <line x1="6" y1="18" x2="18" y2="6" />
          </svg>
        </button>
      </li>
    </ul>

    <!-- Textarea wrapper with inline attach button (bottom-left, OpenRouter style). -->
    <div class="composer__input-wrap">
      <textarea
        ref="textareaRef"
        v-model="internal"
        class="composer__textarea"
        rows="1"
        :placeholder="placeholder"
        :disabled="disabled"
        @keydown="handleKeydown"
        @paste="onPaste"
      />

      <button
        type="button"
        class="composer__attach-btn"
        :title="
          atLimit
            ? `Up to ${maxAttachments} files per message`
            : 'Attach files (PDF, PNG, JPG, MD, TXT)'
        "
        aria-label="Attach files"
        :disabled="disabled || pending || atLimit"
        @click="openFilePicker"
      >
        <!-- Paperclip icon (Feather-style). -->
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path
            d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
          />
        </svg>
      </button>

      <input
        ref="fileInputRef"
        type="file"
        class="composer__file-input"
        :accept="accept"
        multiple
        tabindex="-1"
        @change="onFileInputChange"
      />

      <!-- Drop overlay: only visible while dragging a file over the shell. -->
      <div v-if="isDragging" class="composer__drop-overlay" aria-hidden="true">
        <span class="composer__drop-icon">
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </span>
        <span>Drop files to attach</span>
      </div>
    </div>

    <div class="composer__actions">
      <div class="composer__actions-left">
        <slot name="leading" />
      </div>
      <div class="composer__actions-right">
        <span class="composer__hint">
          <template v-if="atLimit">
            {{ maxAttachments }}-file limit · remove one to add more
          </template>
          <template v-else>
            Enter to send · Shift+Enter for newline
          </template>
        </span>
        <button
          type="submit"
          class="btn btn--primary composer__submit"
          :disabled="!canSend"
        >
          <span v-if="pending" class="spinner" aria-hidden="true" />
          <span>
            {{
              pending
                ? 'Sending…'
                : anyUploading
                  ? 'Uploading…'
                  : 'Send'
            }}
          </span>
        </button>
      </div>
    </div>
  </form>
</template>

<style scoped>
.composer {
  position: relative;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: var(--space-3) var(--space-5) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.composer--dragging {
  background: linear-gradient(
    180deg,
    rgba(139, 92, 246, 0.05),
    rgba(99, 102, 241, 0.08)
  );
}

.composer__input-wrap {
  position: relative;
}

.composer__textarea {
  width: 100%;
  resize: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  /* Leave room on the bottom-left for the attach button. */
  padding: 10px 14px 36px 14px;
  font-family: inherit;
  font-size: var(--text-base);
  line-height: 1.55;
  background: var(--color-surface);
  color: var(--color-text-primary);
  min-height: 64px;
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

.composer__attach-btn {
  position: absolute;
  left: 8px;
  bottom: 6px;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease,
    border-color 0.12s ease, transform 0.12s ease;
}

.composer__attach-btn:hover:not(:disabled) {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  transform: rotate(-8deg);
}

.composer__attach-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.composer__file-input {
  position: absolute;
  inset: auto;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

.composer__drop-overlay {
  position: absolute;
  inset: 0;
  border-radius: var(--radius-md);
  border: 2px dashed var(--color-primary);
  background: rgba(139, 92, 246, 0.08);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: var(--text-sm);
  font-weight: 600;
  pointer-events: none;
  z-index: 3;
}

.composer__drop-icon svg {
  display: block;
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

/* ---- Attachment chips ---- */
.composer__attachments {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attachment-chip {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 6px 6px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  max-width: 260px;
  min-width: 0;
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}

.attachment-chip:hover {
  border-color: var(--color-border-strong);
}

.attachment-chip--uploading {
  border-color: rgba(139, 92, 246, 0.4);
  background: rgba(139, 92, 246, 0.06);
}

.attachment-chip--error {
  border-color: rgba(217, 48, 37, 0.5);
  background: rgba(217, 48, 37, 0.06);
}

.attachment-chip__thumb {
  position: relative;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
  border: 1px solid var(--color-border);
}

.attachment-chip__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.attachment-chip__icon {
  color: var(--color-text-muted);
}

.attachment-chip__icon[data-kind='pdf'] {
  color: #c62828;
}

.attachment-chip__icon[data-kind='text'] {
  color: var(--color-primary);
}

.attachment-chip__progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: rgba(139, 92, 246, 0.2);
}

.attachment-chip__progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #8b5cf6, #6366f1);
  transition: width 0.15s ease;
}

.attachment-chip__meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.attachment-chip__name {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attachment-chip__sub {
  font-size: 10px;
  color: var(--color-text-muted);
}

.attachment-chip--error .attachment-chip__sub {
  color: var(--color-error);
}

.attachment-chip__remove {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: var(--color-surface);
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: background-color 0.12s ease, color 0.12s ease;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.attachment-chip__remove:hover {
  background: rgba(198, 40, 40, 0.1);
  color: #c62828;
}
</style>
