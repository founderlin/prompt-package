<template>
  <Teleport to="body">
    <transition name="dialog">
      <div
        v-if="open"
        class="picker-overlay"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        @mousedown.self="onBackdrop"
      >
        <div class="picker">
          <header class="picker__header">
            <div>
              <h2 :id="titleId" class="picker__title">Add Context</h2>
              <p class="picker__hint text-secondary">
                Pick the context you want the model to read alongside this message.
              </p>
            </div>
            <button
              type="button"
              class="picker__close"
              aria-label="Close"
              @click="onCancel"
            >
              ×
            </button>
          </header>

          <nav class="picker__tabs" role="tablist">
            <button
              v-for="tab in TABS"
              :key="tab.value"
              type="button"
              class="picker__tab"
              :class="{ 'picker__tab--active': activeTab === tab.value }"
              :disabled="tab.disabled"
              :aria-selected="activeTab === tab.value"
              role="tab"
              @click="!tab.disabled && (activeTab = tab.value)"
            >
              <span>{{ tab.label }}</span>
              <span
                v-if="tab.disabled"
                class="picker__tab-badge"
                title="Coming soon"
              >
                Soon
              </span>
            </button>
          </nav>

          <!-- Bla Note tab ---------------------------------------------- -->
          <div v-if="activeTab === 'bla_note'" class="picker__body">
            <input
              v-model="searchInput"
              type="search"
              class="input picker__search"
              placeholder="Search title, content, tags…"
              aria-label="Search Bla Notes"
            />

            <div v-if="loading" class="picker__state">
              <span class="spinner" aria-hidden="true" />
              <span class="text-secondary">Loading notes…</span>
            </div>

            <div
              v-else-if="loadError"
              class="banner banner--error"
              role="alert"
            >
              <strong>Could not load Bla Notes.</strong>
              <span>{{ loadError }}</span>
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                @click="loadNotes"
              >
                Retry
              </button>
            </div>

            <!-- Empty: project has no notes at all -->
            <div
              v-else-if="!notes.length && !searchInput"
              class="picker__empty"
            >
              <p>当前项目还没有 Bla Note。</p>
              <RouterLink
                v-if="projectId"
                :to="{
                  name: 'project-detail',
                  params: { id: String(projectId) },
                  hash: '#project-bla-notes'
                }"
                class="btn btn--primary btn--sm"
                @click="onCancel"
              >
                创建 Bla Note
              </RouterLink>
            </div>

            <!-- Empty: filter matched nothing -->
            <div
              v-else-if="!filteredNotes.length"
              class="picker__empty"
            >
              <p class="text-secondary">
                No notes match “{{ searchInput }}”.
              </p>
            </div>

            <ul v-else class="picker__list">
              <li
                v-for="note in filteredNotes"
                :key="note.id"
                class="picker__item"
                :class="{ 'picker__item--selected': isSelected(note.id) }"
                @click="toggleSelection(note)"
              >
                <div class="picker__item-check" aria-hidden="true">
                  <svg
                    v-if="isSelected(note.id)"
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="3"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                </div>
                <div class="picker__item-main">
                  <h4 class="picker__item-title">{{ note.title }}</h4>
                  <p
                    v-if="note.content_preview"
                    class="picker__item-preview"
                  >
                    {{ note.content_preview }}
                  </p>
                  <div
                    v-if="note.tags && note.tags.length"
                    class="picker__item-tags"
                  >
                    <span
                      v-for="(tag, idx) in note.tags.slice(0, 4)"
                      :key="idx"
                      class="chip chip--primary picker__item-tag"
                    >
                      {{ tag }}
                    </span>
                  </div>
                </div>
                <button
                  v-if="previewNote?.id === note.id"
                  type="button"
                  class="picker__item-preview-btn picker__item-preview-btn--active"
                  :aria-pressed="true"
                  @click.stop="previewNote = null"
                >
                  Hide preview
                </button>
                <button
                  v-else
                  type="button"
                  class="picker__item-preview-btn"
                  :aria-pressed="false"
                  @click.stop="previewNote = note"
                >
                  Preview
                </button>
              </li>
            </ul>

            <!-- Preview pane -->
            <aside
              v-if="previewNote"
              class="picker__preview"
              aria-label="Note preview"
            >
              <header class="picker__preview-head">
                <h4>{{ previewNote.title }}</h4>
                <button
                  type="button"
                  class="picker__close"
                  aria-label="Close preview"
                  @click="previewNote = null"
                >
                  ×
                </button>
              </header>
              <div class="picker__preview-body">
                <pre v-if="previewContent">{{ previewContent }}</pre>
                <p v-else class="text-secondary">
                  {{ previewLoading ? 'Loading…' : '(empty note)' }}
                </p>
              </div>
            </aside>
          </div>

          <!-- Coming-soon tabs ------------------------------------------ -->
          <div
            v-else
            class="picker__body picker__body--placeholder"
          >
            <div class="picker__empty">
              <p class="text-secondary">
                {{ PLACEHOLDER_COPY[activeTab] || 'Coming soon.' }}
              </p>
            </div>
          </div>

          <!-- Action bar ------------------------------------------------ -->
          <footer class="picker__actions">
            <div class="picker__actions-left">
              <span
                v-if="activeTab === 'bla_note' && selected.size"
                class="picker__selected-count"
              >
                {{ selected.size }} selected
              </span>
            </div>
            <div class="picker__actions-right">
              <button
                type="button"
                class="btn btn--ghost"
                @click="onCancel"
              >
                Cancel
              </button>
              <button
                type="button"
                class="btn btn--ghost"
                :disabled="activeTab !== 'bla_note' || !selected.size"
                @click="onInsert"
              >
                Insert to input
              </button>
              <button
                type="button"
                class="btn btn--primary"
                :disabled="activeTab !== 'bla_note' || !selected.size"
                @click="onAttach"
              >
                Attach as context ({{ selected.size || 0 }})
              </button>
            </div>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * ChatContextPicker
 *
 * A modal that lets the user pick context to attach to the *next*
 * message in a chat. Four tabs:
 *
 *   - Bla Note    ← implemented
 *   - Context Pack, History, Attachment ← placeholders
 *
 * Two action modes for the Bla Note tab (the spec):
 *
 *   1. **"Attach as context"** — emit `attach` with the selected
 *      note descriptors. Parent adds them to its `selectedContextItems`
 *      and sends them as `contextItems` in the next message payload.
 *      The note content stays on the server; it's injected into the
 *      LLM prompt but not pasted into the user's textarea.
 *
 *   2. **"Insert to input"** — emit `insert` with a pre-rendered
 *      Markdown block. Parent appends the text to its draft. Useful
 *      when the user wants to edit the quote before sending.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import blaNotesApi from '@/api/blaNotes'
import { describeApiError } from '@/utils/errors'

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: [Number, String], default: null },
  /** Note ids already attached via this picker; keeps state across re-opens. */
  initialSelectedIds: { type: Array, default: () => [] }
})

const emit = defineEmits(['cancel', 'attach', 'insert', 'update:open'])

const uid = Math.random().toString(36).slice(2, 8)
const titleId = `chat-context-picker-title-${uid}`

const TABS = [
  { value: 'bla_note', label: 'Bla Note', disabled: false },
  { value: 'context_pack', label: 'Context Pack', disabled: true },
  { value: 'history', label: 'History', disabled: true },
  { value: 'attachment', label: 'Attachment', disabled: true }
]

const PLACEHOLDER_COPY = {
  context_pack:
    'Context Pack picker lives on the chat sidebar today. A unified picker is on the roadmap.',
  history: 'Import turns from another conversation in this project — coming soon.',
  attachment: 'Attach existing project attachments — coming soon.'
}

const activeTab = ref('bla_note')
const notes = ref([])
const loading = ref(false)
const loadError = ref('')
const searchInput = ref('')

// Selection is a Map<id, descriptor> — Map preserves insertion order so
// the order in the prompt matches the order the user clicked.
const selected = ref(new Map())

const previewNote = ref(null)
const previewContent = ref('')
const previewLoading = ref(false)

const filteredNotes = computed(() => {
  const q = searchInput.value.trim().toLowerCase()
  if (!q) return notes.value
  return notes.value.filter((n) => {
    if ((n.title || '').toLowerCase().includes(q)) return true
    if ((n.content_preview || '').toLowerCase().includes(q)) return true
    const tags = Array.isArray(n.tags) ? n.tags : []
    return tags.some((t) => t.toLowerCase().includes(q))
  })
})

watch(
  () => props.open,
  (next) => {
    if (!next) return
    // Rehydrate selection from parent on each open.
    selected.value = new Map(
      (props.initialSelectedIds || []).map((id) => [id, { id, title: '' }])
    )
    previewNote.value = null
    previewContent.value = ''
    searchInput.value = ''
    loadNotes()
  }
)

watch(previewNote, async (note) => {
  if (!note) {
    previewContent.value = ''
    return
  }
  if (typeof note.content === 'string' && note.content.length) {
    previewContent.value = note.content
    return
  }
  previewContent.value = ''
  previewLoading.value = true
  try {
    const data = await blaNotesApi.get(note.id)
    previewContent.value = data?.note?.content || ''
    // Back-fill the list row so later previews are instant.
    const idx = notes.value.findIndex((n) => n.id === note.id)
    if (idx >= 0) {
      notes.value[idx] = { ...notes.value[idx], content: previewContent.value }
    }
  } catch (_err) {
    previewContent.value = '(failed to load)'
  } finally {
    previewLoading.value = false
  }
})

async function loadNotes() {
  if (!props.projectId) {
    notes.value = []
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    const data = await blaNotesApi.list(props.projectId, { limit: 100 })
    notes.value = Array.isArray(data?.notes) ? data.notes : []
    // Rehydrate selection titles once we have the full list.
    for (const id of selected.value.keys()) {
      const found = notes.value.find((n) => n.id === id)
      if (found) selected.value.set(id, { id, title: found.title })
    }
  } catch (err) {
    loadError.value = describeApiError(err, 'Could not load Bla Notes.')
  } finally {
    loading.value = false
  }
}

function isSelected(id) {
  return selected.value.has(id)
}

function toggleSelection(note) {
  const next = new Map(selected.value)
  if (next.has(note.id)) {
    next.delete(note.id)
  } else {
    next.set(note.id, { id: note.id, title: note.title })
  }
  selected.value = next
}

function onCancel() {
  emit('cancel')
  emit('update:open', false)
}

function onBackdrop() {
  onCancel()
}

/** Emit the selected notes as `{type: 'bla_note', id, title}` items. */
function onAttach() {
  if (activeTab.value !== 'bla_note' || !selected.value.size) return
  const items = Array.from(selected.value.values()).map((v) => ({
    type: 'bla_note',
    id: v.id,
    title: v.title
  }))
  emit('attach', items)
  emit('update:open', false)
}

/**
 * Render the selected notes as a Markdown block suitable for pasting
 * into the composer textarea. The parent appends this to the current
 * draft (no chip persistence — once it's in the textarea it's just
 * part of the user's own text).
 */
async function onInsert() {
  if (activeTab.value !== 'bla_note' || !selected.value.size) return

  // We need full content for each selected note. Fetch any we haven't
  // already loaded (preview may have cached a few).
  const ids = Array.from(selected.value.keys())
  const byId = new Map(notes.value.map((n) => [n.id, n]))

  const full = []
  for (const id of ids) {
    const cached = byId.get(id)
    if (cached && typeof cached.content === 'string' && cached.content.length) {
      full.push(cached)
      continue
    }
    try {
      const data = await blaNotesApi.get(id)
      if (data?.note) full.push(data.note)
    } catch (_err) {
      // Skip silently — user can retry.
    }
  }

  const parts = full.map((n) => {
    const title = (n.title || 'Untitled note').trim()
    const content = (n.content || '').trim()
    return `## Bla Note: ${title}\n\n${content}`
  })
  const block = parts.join('\n\n---\n\n')
  emit('insert', block)
  emit('update:open', false)
}
</script>

<style scoped>
.picker-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-4);
}

.picker {
  background: var(--color-surface);
  width: min(720px, 100%);
  max-height: 85vh;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-3, 0 20px 50px rgba(0, 0, 0, 0.18));
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.picker__header {
  padding: var(--space-4) var(--space-5);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.picker__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 500;
}

.picker__hint {
  margin: 4px 0 0;
  font-size: var(--text-sm);
}

.picker__close {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  flex-shrink: 0;
}
.picker__close:hover {
  background: var(--color-surface-muted);
  color: var(--color-text-primary);
}

.picker__tabs {
  display: flex;
  gap: 4px;
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  overflow-x: auto;
}

.picker__tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border: none;
  background: transparent;
  border-bottom: 2px solid transparent;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-secondary);
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.12s ease, border-color 0.12s ease;
}

.picker__tab:hover:not(:disabled) {
  color: var(--color-text-primary);
}

.picker__tab--active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
}

.picker__tab:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.picker__tab-badge {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
}

.picker__body {
  padding: var(--space-4) var(--space-5);
  flex: 1 1 auto;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 280px;
}

.picker__body--placeholder {
  align-items: center;
  justify-content: center;
}

.picker__search {
  width: 100%;
}

.picker__state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  justify-content: center;
  padding: var(--space-5);
}

.banner {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.banner--error {
  background: var(--color-error-soft);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.picker__empty {
  padding: var(--space-5);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.picker__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.picker__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: 10px 12px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.picker__item:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-muted);
}

.picker__item--selected {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.picker__item-check {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  border: 1.5px solid var(--color-border-strong);
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--color-primary);
  margin-top: 2px;
  background: var(--color-surface);
}

.picker__item--selected .picker__item-check {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.picker__item-main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.picker__item-title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
}

.picker__item-preview {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.picker__item-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.picker__item-tag {
  font-size: 10px;
  padding: 2px 6px;
}

.picker__item-preview-btn {
  font-size: var(--text-xs);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  align-self: center;
}

.picker__item-preview-btn:hover {
  border-color: var(--color-border-strong);
  color: var(--color-text-primary);
}

.picker__item-preview-btn--active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-color: rgba(26, 115, 232, 0.35);
}

.picker__preview {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  max-height: 240px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.picker__preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border);
}

.picker__preview-head h4 {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 500;
}

.picker__preview-body {
  padding: var(--space-3);
  overflow: auto;
}

.picker__preview-body pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.55;
  color: var(--color-text-primary);
}

.picker__actions {
  padding: var(--space-3) var(--space-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.picker__actions-left {
  min-width: 100px;
}

.picker__actions-right {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.picker__selected-count {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.15s ease;
}
.dialog-enter-active .picker,
.dialog-leave-active .picker {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
.dialog-enter-from .picker,
.dialog-leave-to .picker {
  transform: translateY(8px) scale(0.98);
  opacity: 0;
}
</style>
