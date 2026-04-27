<template>
  <div class="pack-view">
    <RouterLink
      :to="{ name: 'project-detail', params: { id: String(props.id) } }"
      class="back-link"
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <polyline points="15 18 9 12 15 6" />
      </svg>
      Back to project
    </RouterLink>

    <div v-if="state === 'loading'" class="state-card">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading Context Pack…</span>
    </div>

    <div v-else-if="state === 'not-found'" class="state-card state-card--empty">
      <h2 class="state-card__title">Context Pack not found</h2>
      <p class="text-secondary">
        It may have been deleted, or you don't have access to it.
      </p>
      <RouterLink
        :to="{ name: 'project-detail', params: { id: String(props.id) } }"
        class="btn btn--primary"
      >
        Back to project
      </RouterLink>
    </div>

    <div v-else-if="state === 'error'" class="banner banner--error" role="alert">
      <strong>Could not load this pack.</strong>
      <span>{{ errorMessage }}</span>
      <button class="btn btn--ghost btn--sm" type="button" @click="loadPack">
        Try again
      </button>
    </div>

    <template v-else-if="pack">
      <header class="pack-view__header card">
        <div class="pack-view__header-text">
          <div v-if="!editingTitle" class="pack-view__title-row">
            <h1 class="pack-view__title">{{ pack.title }}</h1>
            <button
              class="link-btn"
              type="button"
              @click="startEditTitle"
            >
              Rename
            </button>
          </div>
          <form v-else class="pack-view__title-edit" @submit.prevent="saveTitle">
            <input
              ref="titleInput"
              v-model="titleDraft"
              class="input"
              maxlength="160"
              :disabled="savingTitle"
              @keydown.esc="cancelEditTitle"
            />
            <div class="pack-view__title-actions">
              <button
                type="submit"
                class="btn btn--primary btn--sm"
                :disabled="savingTitle || !titleDraft.trim()"
              >
                <span v-if="savingTitle" class="spinner" aria-hidden="true" />
                Save
              </button>
              <button
                type="button"
                class="btn btn--ghost btn--sm"
                :disabled="savingTitle"
                @click="cancelEditTitle"
              >
                Cancel
              </button>
            </div>
          </form>

          <p v-if="titleError" class="pack-view__error">{{ titleError }}</p>

          <dl class="pack-view__meta">
            <div v-if="pack.project?.name">
              <dt>Project</dt>
              <dd>
                <RouterLink
                  :to="{ name: 'project-detail', params: { id: String(pack.project_id) } }"
                  class="link-btn"
                >
                  {{ pack.project.name }}
                </RouterLink>
              </dd>
            </div>
            <div v-if="pack.model">
              <dt>Model</dt>
              <dd>{{ modelLabel(pack.model) }}</dd>
            </div>
            <div>
              <dt>Memories</dt>
              <dd>{{ pack.memory_count || 0 }}</dd>
            </div>
            <div v-if="pack.total_tokens">
              <dt>Tokens</dt>
              <dd>{{ pack.total_tokens }}</dd>
            </div>
            <div v-if="pack.created_at">
              <dt>Created</dt>
              <dd>{{ formatDateTime(pack.created_at) || '—' }}</dd>
            </div>
          </dl>

          <p v-if="pack.instructions" class="pack-view__instructions">
            <span class="pack-view__instructions-label">Extra instructions:</span>
            <span>{{ pack.instructions }}</span>
          </p>
        </div>

        <div class="pack-view__actions">
          <button
            class="btn btn--primary"
            type="button"
            :disabled="!pack.body"
            @click="copyAll"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15V5a2 2 0 0 1 2-2h10" />
            </svg>
            {{ copyState === 'copied' ? 'Copied!' : 'Copy pack' }}
          </button>
          <button
            v-if="!editingBody"
            class="btn btn--ghost"
            type="button"
            @click="startEditBody"
          >
            Edit
          </button>
          <button
            class="btn btn--danger btn--ghost"
            type="button"
            :disabled="deleting"
            @click="onDelete"
          >
            <span v-if="deleting" class="spinner" aria-hidden="true" />
            {{ deleting ? 'Deleting…' : 'Delete' }}
          </button>
        </div>
      </header>

      <section class="card pack-body-card">
        <header class="card-header-row">
          <h3 class="card__title card__title--sm">Pack body (Markdown)</h3>
          <span v-if="!editingBody" class="text-secondary pack-body__char-count">
            {{ (pack.body || '').length }} chars
          </span>
        </header>

        <div v-if="!editingBody" class="pack-body__view">
          <pre class="pack-body__text">{{ pack.body }}</pre>
        </div>

        <form v-else class="pack-body__edit" @submit.prevent="saveBody">
          <textarea
            v-model="bodyDraft"
            class="textarea pack-body__textarea"
            rows="18"
            maxlength="12000"
            :disabled="savingBody"
          />
          <p v-if="bodyError" class="pack-view__error">{{ bodyError }}</p>
          <div class="pack-body__edit-actions">
            <button
              type="button"
              class="btn btn--ghost"
              :disabled="savingBody"
              @click="cancelEditBody"
            >
              Cancel
            </button>
            <button
              type="submit"
              class="btn btn--primary"
              :disabled="savingBody"
            >
              <span v-if="savingBody" class="spinner" aria-hidden="true" />
              {{ savingBody ? 'Saving…' : 'Save changes' }}
            </button>
          </div>
        </form>
      </section>

      <p class="pack-view__footnote text-secondary">
        Source memories: {{ (pack.source_memory_ids || []).length }} ·
        <RouterLink
          :to="{ name: 'project-detail', params: { id: String(pack.project_id) } }"
          class="link-btn"
        >
          View project memories
        </RouterLink>
      </p>
    </template>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import contextPacksApi from '@/api/contextPacks'
import { describeApiError } from '@/utils/errors'
import { formatDateTime } from '@/utils/time'
import { modelLabel } from '@/constants/models'

const props = defineProps({
  id: { type: [String, Number], required: true },
  packId: { type: [String, Number], required: true }
})

const router = useRouter()

const state = ref('loading')
const pack = ref(null)
const errorMessage = ref('')

const editingTitle = ref(false)
const titleDraft = ref('')
const savingTitle = ref(false)
const titleError = ref('')
const titleInput = ref(null)

const editingBody = ref(false)
const bodyDraft = ref('')
const savingBody = ref(false)
const bodyError = ref('')

const deleting = ref(false)
const copyState = ref('idle')
let copyTimer = null

async function loadPack() {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const data = await contextPacksApi.get(props.packId)
    pack.value = data?.context_pack || null
    state.value = pack.value ? 'ready' : 'not-found'
  } catch (err) {
    if (err?.response?.status === 404) {
      state.value = 'not-found'
      pack.value = null
    } else {
      state.value = 'error'
      errorMessage.value = describeApiError(err, 'Could not load this pack.')
    }
  }
}

function startEditTitle() {
  if (!pack.value) return
  titleDraft.value = pack.value.title || ''
  titleError.value = ''
  editingTitle.value = true
  nextTick(() => {
    titleInput.value?.focus()
    titleInput.value?.select?.()
  })
}

function cancelEditTitle() {
  editingTitle.value = false
  titleError.value = ''
}

async function saveTitle() {
  if (!pack.value) return
  const next = titleDraft.value.trim()
  if (!next) {
    titleError.value = 'Title cannot be empty.'
    return
  }
  if (next === pack.value.title) {
    cancelEditTitle()
    return
  }
  savingTitle.value = true
  titleError.value = ''
  try {
    const data = await contextPacksApi.update(pack.value.id, { title: next })
    if (data?.context_pack) {
      pack.value = { ...pack.value, ...data.context_pack }
    }
    editingTitle.value = false
  } catch (err) {
    titleError.value = describeApiError(err, 'Could not save title.')
  } finally {
    savingTitle.value = false
  }
}

function startEditBody() {
  if (!pack.value) return
  bodyDraft.value = pack.value.body || ''
  bodyError.value = ''
  editingBody.value = true
}

function cancelEditBody() {
  editingBody.value = false
  bodyError.value = ''
}

async function saveBody() {
  if (!pack.value) return
  const next = bodyDraft.value
  if (typeof next !== 'string') return
  savingBody.value = true
  bodyError.value = ''
  try {
    const data = await contextPacksApi.update(pack.value.id, { body: next })
    if (data?.context_pack) {
      pack.value = { ...pack.value, ...data.context_pack }
    }
    editingBody.value = false
  } catch (err) {
    bodyError.value = describeApiError(err, 'Could not save changes.')
  } finally {
    savingBody.value = false
  }
}

async function copyAll() {
  if (!pack.value?.body) return
  try {
    await navigator.clipboard.writeText(pack.value.body)
    copyState.value = 'copied'
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copyState.value = 'idle'
    }, 1800)
  } catch (_e) {
    window.alert('Could not copy to clipboard.')
  }
}

async function onDelete() {
  if (!pack.value) return
  const ok = window.confirm('Delete this Context Pack? This cannot be undone.')
  if (!ok) return
  deleting.value = true
  try {
    await contextPacksApi.remove(pack.value.id)
    router.replace({
      name: 'project-detail',
      params: { id: String(pack.value.project_id) }
    })
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not delete the pack.')
    state.value = 'error'
  } finally {
    deleting.value = false
  }
}

watch(
  () => props.packId,
  (next, prev) => {
    if (next && next !== prev) loadPack()
  }
)

onMounted(loadPack)

onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<style scoped>
.pack-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-decoration: none;
  width: fit-content;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  transition: background-color 0.12s ease, color 0.12s ease;
}

.back-link:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
  text-decoration: none;
}

.state-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.state-card--empty {
  flex-direction: column;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-5);
}

.state-card__title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 500;
}

.banner {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
}

.banner strong {
  font-weight: 600;
}

.banner--error {
  background: rgba(198, 40, 40, 0.06);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.pack-view__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  justify-content: space-between;
  align-items: flex-start;
}

.pack-view__header-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.pack-view__title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.pack-view__title {
  margin: 0;
  font-size: var(--text-2xl, 22px);
  font-weight: 500;
  word-break: break-word;
}

.pack-view__title-edit {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pack-view__title-actions {
  display: flex;
  gap: var(--space-2);
}

.pack-view__error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-error);
}

.pack-view__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin: var(--space-2) 0 0;
}

.pack-view__meta div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pack-view__meta dt {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  margin: 0;
}

.pack-view__meta dd {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.pack-view__instructions {
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pack-view__instructions-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.pack-view__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.link-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--color-primary);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.input,
.textarea {
  width: 100%;
  padding: 10px 12px;
  font-size: var(--text-sm);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-primary);
  font-family: inherit;
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}

.input:focus,
.textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.textarea {
  resize: vertical;
  line-height: 1.55;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: var(--text-sm);
}

.pack-body-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.pack-body__char-count {
  font-size: var(--text-xs);
}

.pack-body__view {
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-4);
  max-height: 640px;
  overflow: auto;
}

.pack-body__text {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
}

.pack-body__textarea {
  min-height: 320px;
}

.pack-body__edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.pack-view__footnote {
  margin: 0;
  font-size: var(--text-sm);
}

@media (max-width: 720px) {
  .pack-view__header {
    flex-direction: column;
  }
  .pack-view__actions {
    width: 100%;
  }
  .pack-view__actions .btn {
    flex: 1;
  }
}
</style>
