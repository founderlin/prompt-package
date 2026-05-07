<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import apiClient from '@/api/client'
import attachmentsApi from '@/api/attachments'
import { modelLabel } from '@/constants/models'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps({
  message: { type: Object, required: true },
  highlighted: { type: Boolean, default: false },
  /** Whether this message can be retried (assistants only, disabled while pending). */
  canRetry: { type: Boolean, default: false }
})

const emit = defineEmits(['copy', 'retry', 'delete', 'edit'])

const copyFeedback = ref('')
let copyFeedbackTimer = null

// Inline edit state — only used for user messages.
const editing = ref(false)
const editBuffer = ref('')
const editSubmitting = ref(false)
const editError = ref('')
const editTextareaRef = ref(null)
const editFileInputRef = ref(null)

// Attachments inside the editor.
// Shape per entry:
//   { clientId, id, filename, size_bytes, kind, status: 'done'|'uploading'|'error',
//     existing: true | false, previewUrl?, progress?, error? }
// `existing: true` means the attachment is already saved on this message;
// removing it from the editor means we want it deleted on save.
const editAttachments = ref([])
const EDIT_MAX_ATTACH = 8
const EDIT_ALLOWED_MIME = new Set([
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/webp',
  'image/gif',
  'application/pdf',
  'text/plain',
  'text/markdown',
  'text/x-markdown'
])
const EDIT_ALLOWED_EXT = /\.(png|jpe?g|webp|gif|pdf|md|markdown|txt)$/i

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

const modelText = computed(() => {
  if (!isAssistant.value) return ''
  return props.message.model ? modelLabel(props.message.model) : ''
})

const tokensText = computed(() => {
  if (!isAssistant.value) return ''
  return props.message.total_tokens != null
    ? `${props.message.total_tokens} tok`
    : ''
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

/** Show footer only for persisted, non-system messages. */
const showFooter = computed(
  () => !isSystem.value && props.message.id != null
)

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
  if (copyFeedbackTimer) {
    clearTimeout(copyFeedbackTimer)
    copyFeedbackTimer = null
  }
  // If the editor is still open when the bubble unmounts (e.g. the
  // whole conversation got swapped away), clean up any detached
  // attachments the user uploaded but never committed.
  if (editing.value && editAttachments.value.length) {
    _cleanupAbandonedEditUploads(editAttachments.value)
    _revokeEditPreviews(editAttachments.value)
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

function onCopyClick() {
  emit('copy', props.message)
  copyFeedback.value = 'Copied'
  if (copyFeedbackTimer) clearTimeout(copyFeedbackTimer)
  copyFeedbackTimer = setTimeout(() => {
    copyFeedback.value = ''
    copyFeedbackTimer = null
  }, 1200)
}

// Upper-right corner hover action: same "copy the plain content" as the
// footer button, but visible without scrolling down to read the meta
// row. Using a dedicated handler (vs reusing onCopyClick) lets us add
// its own micro-feedback state in the future without coupling.
function onHoverCopyClick() {
  onCopyClick()
}

function onRetryClick() {
  if (!props.canRetry) return
  emit('retry', props.message)
}

// ---- Inline edit (user messages only) -----
function onEditClick() {
  if (!canEdit.value) return
  editing.value = true
  editBuffer.value = props.message.content || ''
  editError.value = ''
  // Seed the editor with a copy of the current attachments so the user
  // can see them right away, delete any they don't want anymore, or
  // add new ones on top.
  editAttachments.value = (attachments.value || []).map((a) => ({
    clientId: `att-existing-${a.id}`,
    id: a.id,
    filename: a.filename,
    size_bytes: a.size_bytes,
    kind: a.kind,
    status: 'done',
    existing: true,
    previewUrl: null
  }))
  // Focus the textarea on the next frame so the caret lands inside it.
  setTimeout(() => {
    const el = editTextareaRef.value
    if (el) {
      el.focus()
      // Put cursor at the end for a natural "continue typing" feel.
      const n = el.value.length
      try {
        el.setSelectionRange(n, n)
      } catch (_e) {
        /* older browsers */
      }
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, 360)}px`
    }
  }, 0)
}

function _revokeEditPreviews(list) {
  for (const a of list || []) {
    if (a.previewUrl && typeof URL?.revokeObjectURL === 'function') {
      try {
        URL.revokeObjectURL(a.previewUrl)
      } catch (_e) {
        /* ignore */
      }
    }
  }
}

async function _cleanupAbandonedEditUploads(list) {
  // When the user cancels the edit, any files they uploaded during the
  // editor session are now orphaned (detached, belonging to this convo).
  // Best-effort delete them so they don't linger as half-committed rows.
  const convoId = props.message?.conversation_id
  if (!convoId) return
  for (const a of list || []) {
    if (a.existing) continue
    if (a.status !== 'done' || a.id == null) continue
    try {
      await attachmentsApi.remove(convoId, a.id)
    } catch (_e) {
      /* best effort */
    }
  }
}

function onEditCancel() {
  const snapshot = editAttachments.value
  editing.value = false
  editBuffer.value = ''
  editError.value = ''
  // Fire and forget — we don't want to block the UI on cleanup.
  _cleanupAbandonedEditUploads(snapshot)
  _revokeEditPreviews(snapshot)
  editAttachments.value = []
}

function onEditInput(event) {
  editBuffer.value = event.target.value
  const el = event.target
  if (el) {
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 360)}px`
  }
}

function onEditKeydown(event) {
  // Cmd/Ctrl + Enter → submit. Bare Enter keeps newline (this isn't
  // a single-turn form).
  if (event.key === 'Escape') {
    event.preventDefault()
    onEditCancel()
    return
  }
  if (
    event.key === 'Enter' &&
    (event.metaKey || event.ctrlKey) &&
    !event.isComposing
  ) {
    event.preventDefault()
    onEditSubmit()
  }
}

async function onEditSubmit() {
  const next = editBuffer.value.trim()
  if (!next) {
    editError.value = 'Message cannot be empty.'
    return
  }
  const anyUploading = editAttachments.value.some(
    (a) => a.status === 'uploading'
  )
  if (anyUploading) {
    editError.value = 'Wait for attachments to finish uploading.'
    return
  }
  // Drop failed upload rows before sending so they don't poison the list.
  editAttachments.value = editAttachments.value.filter(
    (a) => a.status !== 'error'
  )

  const currentAttachmentIds = (attachments.value || [])
    .map((a) => a.id)
    .filter((x) => x != null)
  const nextAttachmentIds = editAttachments.value
    .filter((a) => a.status === 'done' && a.id != null)
    .map((a) => a.id)

  const attachmentsChanged =
    currentAttachmentIds.length !== nextAttachmentIds.length ||
    currentAttachmentIds.some((id, i) => id !== nextAttachmentIds[i])
  const contentChanged = next !== (props.message.content || '').trim()

  if (!contentChanged && !attachmentsChanged) {
    // Nothing to do. Close without bothering the server.
    onEditCancel()
    return
  }

  editError.value = ''
  editSubmitting.value = true
  try {
    await new Promise((resolve, reject) => {
      emit('edit', {
        message: props.message,
        content: next,
        attachmentIds: nextAttachmentIds,
        resolve,
        reject
      })
    })
    editing.value = false
    editBuffer.value = ''
    // The server now owns the attachment binding — `existing: false`
    // rows from the editor have been committed, while any removed ones
    // were deleted via rebind. We don't need to call cleanup here.
    _revokeEditPreviews(editAttachments.value)
    editAttachments.value = []
  } catch (err) {
    editError.value =
      err?.message || 'Could not save this edit. Try again.'
  } finally {
    editSubmitting.value = false
  }
}

const canEdit = computed(
  () => isUser.value && props.message.id != null
)

// ---- Edit-mode attachment controls -----
function _isAllowedEditFile(file) {
  if (!file) return false
  if (EDIT_ALLOWED_MIME.has(file.type)) return true
  return EDIT_ALLOWED_EXT.test(file.name || '')
}

function _kindForEditFile(file) {
  const type = file?.type || ''
  if (type.startsWith('image/')) return 'image'
  if (
    type === 'application/pdf' ||
    /\.pdf$/i.test(file?.name || '')
  ) {
    return 'pdf'
  }
  return 'text'
}

function _nextEditClientId() {
  return `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function openEditFilePicker() {
  if (editSubmitting.value) return
  if (editAttachments.value.length >= EDIT_MAX_ATTACH) return
  editFileInputRef.value?.click()
}

async function onEditFileInputChange(event) {
  const files = Array.from(event.target?.files || [])
  if (event.target) event.target.value = ''
  if (!files.length) return
  await _uploadEditFiles(files)
}

async function _uploadEditFiles(files) {
  const convoId = props.message?.conversation_id
  if (!convoId) return
  const accepted = []
  const rejected = []
  for (const f of files) {
    if (editAttachments.value.length + accepted.length >= EDIT_MAX_ATTACH) {
      rejected.push('limit')
      continue
    }
    if (!_isAllowedEditFile(f)) {
      rejected.push('type')
      continue
    }
    if (f.size > 10 * 1024 * 1024) {
      rejected.push('size')
      continue
    }
    accepted.push(f)
  }
  if (rejected.length) {
    const messages = []
    if (rejected.includes('limit'))
      messages.push(`up to ${EDIT_MAX_ATTACH} files per message`)
    if (rejected.includes('type'))
      messages.push('only PDF, PNG, JPG, WEBP, GIF, TXT, MD allowed')
    if (rejected.includes('size')) messages.push('max 10 MB per file')
    editError.value = `Some files were skipped: ${messages.join('; ')}.`
  }

  const entries = accepted.map((f) => ({
    clientId: _nextEditClientId(),
    id: null,
    filename: f.name,
    size_bytes: f.size,
    kind: _kindForEditFile(f),
    status: 'uploading',
    existing: false,
    progress: 0,
    previewUrl:
      f.type.startsWith('image/') &&
      typeof URL?.createObjectURL === 'function'
        ? URL.createObjectURL(f)
        : null,
    error: null
  }))
  editAttachments.value = [...editAttachments.value, ...entries]

  // Kick off uploads in parallel but guarded by editor-session identity
  // (if the user cancels mid-upload we don't want to then mutate the
  // closed-out list).
  for (const entry of entries) {
    try {
      const data = await attachmentsApi.upload(
        convoId,
        files[entries.indexOf(entry)],
        {
          onProgress: (frac) => {
            const row = editAttachments.value.find(
              (r) => r.clientId === entry.clientId
            )
            if (row) row.progress = frac
          }
        }
      )
      const att = data?.attachment || {}
      const row = editAttachments.value.find(
        (r) => r.clientId === entry.clientId
      )
      if (row) {
        row.status = 'done'
        row.progress = 1
        row.id = att.id
        row.filename = att.filename || row.filename
        row.size_bytes = att.size_bytes || row.size_bytes
        row.kind = att.kind || row.kind
      }
    } catch (err) {
      const row = editAttachments.value.find(
        (r) => r.clientId === entry.clientId
      )
      if (row) {
        row.status = 'error'
        row.error = err?.message || 'Upload failed'
      }
    }
  }
}

async function removeEditAttachment(att) {
  if (!att) return
  // Delete-from-server is only safe for rows we uploaded during this
  // edit session (they're still detached). Attachments that are
  // ``existing`` stay on the backend — rebind will delete them when
  // the user hits "Save & Regenerate".
  if (!att.existing && att.id != null && props.message?.conversation_id) {
    try {
      await attachmentsApi.remove(props.message.conversation_id, att.id)
    } catch (_e) {
      /* best effort */
    }
  }
  if (att.previewUrl && typeof URL?.revokeObjectURL === 'function') {
    try {
      URL.revokeObjectURL(att.previewUrl)
    } catch (_e) {
      /* ignore */
    }
  }
  editAttachments.value = editAttachments.value.filter(
    (a) => a.clientId !== att.clientId
  )
}

function formatEditAttachmentBytes(n) {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

const editAtLimit = computed(
  () => editAttachments.value.length >= EDIT_MAX_ATTACH
)

// ---- Markdown rendering (assistants only) ---------------------------------
// User / system turns stay plain-text so `*star*` and friends don't
// accidentally turn into emphasis. Assistant replies go through
// marked + DOMPurify so code fences, tables, and links all render like
// they do on OpenRouter / ChatGPT.
const renderedContent = computed(() => {
  if (!isAssistant.value) return ''
  return renderMarkdown(props.message.content || '')
})

// Track per-code-block copy feedback so we can flash "Copied" on the
// individual button the user clicked (not the whole bubble).
const codeCopyFeedback = ref(new WeakMap())
const codeCopyFeedbackBumper = ref(0) // force-recompute tooltips/labels

function onContentClick(event) {
  // Event delegation: the copy button sits inside the v-html'd markdown
  // tree, so we catch the click here on the container. Each copy button
  // is tagged with `data-copy-code`; when we find one, we walk up to its
  // enclosing `.md-codeblock` and read the visible source straight out
  // of the rendered <code> element's textContent.
  //
  // Why textContent instead of a pre-baked attribute? It guarantees
  // "what you see in this block is exactly what gets copied" — no risk
  // of the copy payload diverging from what's visible (which could
  // previously happen if marked grouped content unexpectedly, or if
  // the data-code attribute got altered/overwritten by sanitization).
  const btn = event.target?.closest?.('[data-copy-code]')
  if (!btn) return
  event.preventDefault()
  event.stopPropagation()
  const block = btn.closest('.md-codeblock')
  const codeEl = block?.querySelector('pre code')
  // Use innerText so visual line breaks are preserved (textContent
  // collapses them in some rendering paths). Fallback to textContent
  // for older engines where innerText isn't defined on <code>.
  const raw = codeEl
    ? (typeof codeEl.innerText === 'string' ? codeEl.innerText : codeEl.textContent) || ''
    : ''
  if (!raw) return

  const finish = () => {
    const labelEl = btn.querySelector('.md-codeblock__copy-label')
    const original = labelEl?.textContent
    if (labelEl) labelEl.textContent = 'Copied'
    btn.classList.add('md-codeblock__copy--done')
    setTimeout(() => {
      if (labelEl && original != null) labelEl.textContent = original
      btn.classList.remove('md-codeblock__copy--done')
    }, 1200)
  }

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(raw).then(finish, () => {
      fallbackCopy(raw)
      finish()
    })
  } else {
    fallbackCopy(raw)
    finish()
  }

  // NOTE: do NOT `emit('copy', ...)` here. The parent's copy handler
  // (see ProjectChatView.handleCopyMessage) unconditionally writes
  // `msg.content` — i.e. the full assistant reply — to the clipboard,
  // which would race with and OVERWRITE the code-block copy we just
  // performed above. That was the "copy copies the whole conversation"
  // bug. Code-block copies are strictly a local UI action; the parent
  // doesn't need to know about them. Only the message-level Copy button
  // (`onCopyClick`) should emit 'copy'.

  // Suppress unused-local warnings from older editors.
  void codeCopyFeedback.value
  void codeCopyFeedbackBumper.value
}

function fallbackCopy(text) {
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  } catch (_e) {
    /* ignore */
  }
}

function onDeleteClick() {
  const ok = window.confirm(
    isUser.value
      ? 'Delete this message and everything after it in this blabla?'
      : 'Delete this reply?'
  )
  if (!ok) return
  emit('delete', props.message)
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
      <!-- Content wrapper carries the hover-revealed corner actions
           (Copy / Edit). The actual content node sits inside so the
           button positioning is tied to the bubble bounds, not the
           whole row. -->
      <div
        v-if="message.content || editing"
        class="bubble__content-wrap"
        :class="{ 'bubble__content-wrap--editing': editing }"
      >
        <!-- Corner actions: only shown when we're not editing and the
             message has a stable id (no in-flight placeholders). -->
        <div
          v-if="!editing && !isSystem && message.id != null"
          class="bubble__corner-actions"
          aria-hidden="false"
        >
          <button
            type="button"
            class="bubble-corner-btn"
            :title="copyFeedback || 'Copy message'"
            :aria-label="copyFeedback || 'Copy message'"
            @click="onHoverCopyClick"
          >
            <svg
              v-if="!copyFeedback"
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <svg
              v-else
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </button>
          <button
            v-if="canEdit"
            type="button"
            class="bubble-corner-btn"
            title="Edit message"
            aria-label="Edit message"
            @click="onEditClick"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4z" />
            </svg>
          </button>
        </div>

        <!-- Inline editor: replaces the content for user bubbles while
             editing. Save & Regenerate triggers /regenerate on the
             server with the edited content as the new user turn. -->
        <div v-if="editing" class="bubble__editor">
          <textarea
            ref="editTextareaRef"
            class="bubble__editor-input"
            :value="editBuffer"
            rows="2"
            :disabled="editSubmitting"
            @input="onEditInput"
            @keydown="onEditKeydown"
          />

          <!-- Attachments the regenerated turn will carry. Existing +
               newly uploaded rows sit in the same chip list; removing
               either kind just drops it from the new set that gets sent
               to the server. -->
          <ul
            v-if="editAttachments.length"
            class="bubble__editor-attachments"
            aria-label="Edited attachments"
          >
            <li
              v-for="att in editAttachments"
              :key="att.clientId"
              class="edit-attachment-chip"
              :class="{
                'edit-attachment-chip--uploading': att.status === 'uploading',
                'edit-attachment-chip--error': att.status === 'error'
              }"
            >
              <div class="edit-attachment-chip__thumb">
                <img
                  v-if="att.kind === 'image' && att.previewUrl"
                  :src="att.previewUrl"
                  :alt="att.filename"
                />
                <span
                  v-else
                  class="edit-attachment-chip__icon"
                  :data-kind="(att.kind || 'file').toLowerCase()"
                  aria-hidden="true"
                >
                  <svg
                    v-if="att.kind === 'pdf'"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  <svg
                    v-else
                    width="16"
                    height="16"
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
                  class="edit-attachment-chip__progress"
                >
                  <div
                    class="edit-attachment-chip__progress-bar"
                    :style="{ width: `${Math.round((att.progress || 0) * 100)}%` }"
                  />
                </div>
              </div>
              <div class="edit-attachment-chip__meta">
                <span class="edit-attachment-chip__name" :title="att.filename">
                  {{ att.filename }}
                </span>
                <span class="edit-attachment-chip__sub">
                  <template v-if="att.status === 'uploading'">
                    Uploading… {{ Math.round((att.progress || 0) * 100) }}%
                  </template>
                  <template v-else-if="att.status === 'error'">
                    {{ att.error || 'Upload failed' }}
                  </template>
                  <template v-else>
                    {{ formatEditAttachmentBytes(att.size_bytes) }}
                  </template>
                </span>
              </div>
              <button
                type="button"
                class="edit-attachment-chip__remove"
                :aria-label="`Remove ${att.filename}`"
                :disabled="editSubmitting"
                @click="removeEditAttachment(att)"
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
                >
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="6" y1="18" x2="18" y2="6" />
                </svg>
              </button>
            </li>
          </ul>

          <p v-if="editError" class="bubble__editor-error" role="alert">
            {{ editError }}
          </p>

          <div class="bubble__editor-actions">
            <button
              type="button"
              class="bubble__editor-attach-btn"
              :title="
                editAtLimit
                  ? `Up to ${EDIT_MAX_ATTACH} files`
                  : 'Add attachment'
              "
              aria-label="Add attachment"
              :disabled="editSubmitting || editAtLimit"
              @click="openEditFilePicker"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.9"
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
              ref="editFileInputRef"
              type="file"
              class="bubble__editor-file-input"
              accept="image/png,image/jpeg,image/jpg,image/webp,image/gif,application/pdf,text/plain,text/markdown,.md,.txt"
              multiple
              tabindex="-1"
              @change="onEditFileInputChange"
            />

            <span class="bubble__editor-hint">
              ⌘/Ctrl + Enter to save · Esc to cancel
            </span>
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="editSubmitting"
              @click="onEditCancel"
            >
              Cancel
            </button>
            <button
              type="button"
              class="btn btn--primary btn--sm"
              :disabled="editSubmitting || !editBuffer.trim()"
              @click="onEditSubmit"
            >
              <span v-if="editSubmitting" class="spinner" aria-hidden="true" />
              <span>{{ editSubmitting ? 'Saving…' : 'Save & Regenerate' }}</span>
            </button>
          </div>
        </div>

        <!-- Normal rendered content -->
        <div
          v-else-if="isAssistant"
          class="bubble__content bubble__content--md"
          v-html="renderedContent"
          @click="onContentClick"
        />
        <div
          v-else
          class="bubble__content"
        >{{ message.content }}</div>
      </div>

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

      <!-- Single-line footer: actions first (retry → copy → delete), then
           meta text (model · tokens · time for assistants; time only for
           users). Order is fixed so ChatGPT/OpenRouter-style power-user
           muscle memory works in both columns. -->
      <div
        v-if="showFooter"
        class="bubble__footer"
        :class="{ 'bubble__footer--user': isUser }"
      >
        <button
          type="button"
          class="bubble-action"
          :disabled="!canRetry"
          :title="
            canRetry
              ? isUser
                ? 'Regenerate the reply to this message'
                : 'Regenerate this reply'
              : 'Busy — try again in a moment'
          "
          aria-label="Retry"
          @click="onRetryClick"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.9"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
        </button>

        <button
          type="button"
          class="bubble-action"
          :title="copyFeedback || 'Copy message'"
          :aria-label="copyFeedback || 'Copy message'"
          @click="onCopyClick"
        >
          <svg
            v-if="!copyFeedback"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.9"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <rect x="9" y="9" width="13" height="13" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          <svg
            v-else
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </button>

        <button
          type="button"
          class="bubble-action bubble-action--danger"
          :title="
            isUser
              ? 'Delete this message and everything after it'
              : 'Delete this reply'
          "
          aria-label="Delete"
          @click="onDeleteClick"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.9"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
            <path d="M10 11v6M14 11v6" />
            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>

        <!-- Meta text — fixed order: model · tokens · time for assistants,
             time only for user messages. -->
        <span v-if="modelText" class="bubble__meta-text bubble__model">
          {{ modelText }}
        </span>
        <span v-if="tokensText" class="bubble__meta-text bubble__tokens">
          {{ tokensText }}
        </span>
        <span v-if="time" class="bubble__meta-text bubble__time">
          {{ time }}
        </span>
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
  max-width: min(820px, 82%);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Content wrapper: relative positioning host for the corner action
   group. No background/border of its own — the inner .bubble__content
   provides the actual bubble shell. */
.bubble__content-wrap {
  position: relative;
}

.bubble__content-wrap--editing {
  width: 100%;
}

/* Hover-revealed Copy / Edit cluster pinned to the top-right corner of
   the bubble — same position for both columns so it reads as "the
   bubble's own corner", not "the side closer to the avatar". */
.bubble__corner-actions {
  position: absolute;
  top: 4px;
  right: 4px;
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border-radius: 999px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.14s ease, transform 0.14s ease;
  transform: translateY(2px);
  z-index: 2;
}

.bubble:hover .bubble__corner-actions,
.bubble:focus-within .bubble__corner-actions {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.bubble-corner-btn {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  border-radius: 999px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.12s ease, color 0.12s ease;
  padding: 0;
  font: inherit;
}

.bubble-corner-btn:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.bubble-corner-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* Inline edit: textarea + action bar replace the content while editing.
   Textarea visually lives inside a bubble-looking shell so the feel is
   "you're editing the bubble in place". */
.bubble__editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-lg);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
  min-width: min(480px, 100%);
}

.bubble--user .bubble__editor {
  /* When editing a user message, keep the same visual alignment (right
     column) by letting flex-end on the parent position us. */
  width: 100%;
}

.bubble__editor-input {
  width: 100%;
  min-height: 48px;
  max-height: 360px;
  resize: none;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--color-text-primary);
  font-family: inherit;
  font-size: var(--text-md);
  line-height: 1.6;
  padding: 0;
}

.bubble__editor-input:disabled {
  color: var(--color-text-muted);
}

.bubble__editor-error {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-error);
}

.bubble__editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.bubble__editor-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-right: auto;
}

/* Edit-mode attachment chips live right below the textarea. Visually
   similar to ChatComposer's chips but scoped here so the styling can
   evolve independently. */
.bubble__editor-attachments {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.edit-attachment-chip {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px 5px 5px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  max-width: 240px;
  min-width: 0;
}

.edit-attachment-chip--uploading {
  border-color: rgba(139, 92, 246, 0.4);
  background: rgba(139, 92, 246, 0.06);
}

.edit-attachment-chip--error {
  border-color: rgba(217, 48, 37, 0.5);
  background: rgba(217, 48, 37, 0.06);
}

.edit-attachment-chip__thumb {
  position: relative;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  flex-shrink: 0;
  border: 1px solid var(--color-border);
}

.edit-attachment-chip__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.edit-attachment-chip__icon {
  color: var(--color-text-muted);
}

.edit-attachment-chip__icon[data-kind='pdf'] {
  color: #c62828;
}

.edit-attachment-chip__icon[data-kind='text'] {
  color: var(--color-primary);
}

.edit-attachment-chip__progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: rgba(139, 92, 246, 0.2);
}

.edit-attachment-chip__progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #8b5cf6, #6366f1);
  transition: width 0.15s ease;
}

.edit-attachment-chip__meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.edit-attachment-chip__name {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.edit-attachment-chip__sub {
  font-size: 10px;
  color: var(--color-text-muted);
}

.edit-attachment-chip--error .edit-attachment-chip__sub {
  color: var(--color-error);
}

.edit-attachment-chip__remove {
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
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  transition: background-color 0.12s ease, color 0.12s ease;
}

.edit-attachment-chip__remove:hover:not(:disabled) {
  background: rgba(198, 40, 40, 0.1);
  color: #c62828;
}

.edit-attachment-chip__remove:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.bubble__editor-attach-btn {
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
    transform 0.12s ease;
  padding: 0;
}

.bubble__editor-attach-btn:hover:not(:disabled) {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  transform: rotate(-8deg);
}

.bubble__editor-attach-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.bubble__editor-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

@media (hover: none) {
  /* Touch: keep the corner actions always visible so they stay reachable. */
  .bubble__corner-actions {
    opacity: 1;
    pointer-events: auto;
    transform: none;
  }
}

.bubble--user .bubble__body {
  align-items: flex-end;
}

.bubble__content {
  background: var(--color-surface);
  color: var(--color-text-primary);
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-1);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: var(--text-md);
}

/* Markdown variant drops pre-wrap so rendered block elements (lists,
   tables, pre) don't get their own pre-wrap applied on top of the
   browser defaults. Inline whitespace is still respected via the
   marked config (breaks: true converts \n to <br> inside paragraphs). */
.bubble__content--md {
  white-space: normal;
  /* Leave a touch more vertical air so headings/blockquotes breathe. */
  padding: 14px 18px;
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

/* Single footer row: retry / copy / delete / meta-text, in this exact
   order. For user bubbles the row flips with flex-direction: row-reverse
   so the buttons still read "retry → copy → delete → meta" when scanning
   from the outside edge of the bubble inward (i.e. the first thing next
   to the bubble on the outside is retry, like OpenRouter/ChatGPT). */
.bubble__footer {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  color: var(--color-text-muted);
}

.bubble__footer--user {
  flex-direction: row-reverse;
}

/* Actions fade in on hover to keep the feed calm when scanning. */
.bubble__footer .bubble-action,
.bubble__footer .bubble__meta-text {
  opacity: 0;
  transition: opacity 0.15s ease;
}

.bubble:hover .bubble__footer .bubble-action,
.bubble:focus-within .bubble__footer .bubble-action,
.bubble:hover .bubble__footer .bubble__meta-text,
.bubble:focus-within .bubble__footer .bubble__meta-text {
  opacity: 1;
}

/* Keep the timestamp + model meta always visible so a turn never looks
   timeless at rest — only the action buttons hide. */
.bubble__footer .bubble__meta-text {
  opacity: 0.7;
}

.bubble:hover .bubble__footer .bubble__meta-text,
.bubble:focus-within .bubble__footer .bubble__meta-text {
  opacity: 1;
}

.bubble__meta-text {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
}

/* Small dot separators between meta items. Using ::before so it only
   appears between siblings, not before the first one. */
.bubble__meta-text + .bubble__meta-text::before {
  content: '·';
  margin: 0 6px;
  color: var(--color-text-muted);
  opacity: 0.6;
}

.bubble__model {
  font-weight: 500;
}

.bubble-action {
  width: 24px;
  height: 24px;
  padding: 0;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease,
    border-color 0.12s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.bubble-action:hover:not(:disabled) {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
  border-color: var(--color-border);
}

.bubble-action--danger:hover:not(:disabled) {
  background: rgba(198, 40, 40, 0.1);
  color: #c62828;
  border-color: rgba(198, 40, 40, 0.35);
}

.bubble-action:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

@media (hover: none) {
  /* Touch devices never trigger hover — keep everything visible. */
  .bubble__footer .bubble-action,
  .bubble__footer .bubble__meta-text {
    opacity: 1;
  }
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

/* ---- Markdown-rendered assistant content ----
   These rules target HTML that comes out of marked + DOMPurify. Because
   the HTML is injected via v-html, Vue's scoped CSS wouldn't reach it
   without :deep() — so every selector here is wrapped accordingly. */

.bubble__content--md :deep(p) {
  margin: 0 0 10px;
  line-height: 1.6;
}

.bubble__content--md :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble__content--md :deep(h1),
.bubble__content--md :deep(h2),
.bubble__content--md :deep(h3),
.bubble__content--md :deep(h4),
.bubble__content--md :deep(h5),
.bubble__content--md :deep(h6) {
  margin: 16px 0 8px;
  font-weight: 600;
  line-height: 1.3;
}

.bubble__content--md :deep(h1) { font-size: 1.45em; }
.bubble__content--md :deep(h2) { font-size: 1.28em; }
.bubble__content--md :deep(h3) { font-size: 1.14em; }
.bubble__content--md :deep(h4) { font-size: 1.05em; }
.bubble__content--md :deep(h5),
.bubble__content--md :deep(h6) { font-size: 1em; }

.bubble__content--md :deep(ul),
.bubble__content--md :deep(ol) {
  margin: 0 0 10px;
  padding-left: 1.5em;
}

.bubble__content--md :deep(li) {
  margin: 2px 0;
  line-height: 1.55;
}

.bubble__content--md :deep(li > p) {
  margin: 2px 0;
}

.bubble__content--md :deep(a) {
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.bubble__content--md :deep(a:hover) {
  text-decoration: underline;
  opacity: 0.85;
}

.bubble__content--md :deep(blockquote) {
  margin: 10px 0;
  padding: 6px 14px;
  border-left: 3px solid var(--color-border-strong);
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.bubble__content--md :deep(hr) {
  border: 0;
  border-top: 1px solid var(--color-border);
  margin: 14px 0;
}

.bubble__content--md :deep(table) {
  border-collapse: collapse;
  margin: 10px 0;
  display: block;
  overflow-x: auto;
  font-size: 0.95em;
  max-width: 100%;
}

.bubble__content--md :deep(th),
.bubble__content--md :deep(td) {
  border: 1px solid var(--color-border);
  padding: 6px 10px;
  text-align: left;
}

.bubble__content--md :deep(th) {
  background: var(--color-surface-muted);
  font-weight: 600;
}

.bubble__content--md :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-sm);
  margin: 6px 0;
}

/* Inline code (single backticks). */
.bubble__content--md :deep(code) {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.92em;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  padding: 1px 5px;
  border-radius: 4px;
  word-break: break-word;
}

/* ---- Code blocks (triple backticks) ---- */
.bubble__content--md :deep(.md-codeblock) {
  position: relative;
  margin: 10px 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: #f8fafc;
}

.bubble__content--md :deep(.md-codeblock__header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  background: var(--color-surface-muted);
  border-bottom: 1px solid var(--color-border);
  font-size: 11px;
  color: var(--color-text-muted);
}

.bubble__content--md :deep(.md-codeblock__lang) {
  text-transform: lowercase;
  letter-spacing: 0.3px;
  font-weight: 500;
}

.bubble__content--md :deep(.md-codeblock__copy) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid transparent;
  background: transparent;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--color-text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background-color 0.12s ease, border-color 0.12s ease,
    color 0.12s ease;
  font: inherit;
  font-size: 11px;
}

.bubble__content--md :deep(.md-codeblock__copy:hover) {
  background: var(--color-surface);
  border-color: var(--color-border);
  color: var(--color-text-primary);
}

.bubble__content--md :deep(.md-codeblock__copy--done) {
  background: rgba(46, 125, 50, 0.1);
  border-color: rgba(46, 125, 50, 0.35);
  color: #1b5e20;
}

.bubble__content--md :deep(.md-codeblock__pre) {
  margin: 0;
  padding: 10px 14px;
  overflow-x: auto;
  background: transparent;
}

.bubble__content--md :deep(.md-codeblock__pre code) {
  /* Reset the inline-code chip styling for code that's already inside a <pre>. */
  background: transparent;
  border: 0;
  padding: 0;
  font-size: 0.92em;
  line-height: 1.55;
  color: inherit;
  word-break: normal;
  white-space: pre;
}

/* Dim the thumb during hover reveals, like OpenRouter. */
.bubble__content--md :deep(.md-codeblock:hover) {
  border-color: var(--color-border-strong);
}
</style>
