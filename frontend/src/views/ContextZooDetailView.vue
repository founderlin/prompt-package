<template>
  <div class="zoo-detail">
    <RouterLink to="/context-zoo" class="back-link">
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
        <polyline points="15 18 9 12 15 6" />
      </svg>
      Back to Context Zoo
    </RouterLink>

    <!-- LOADING -->
    <div v-if="state === 'loading'" class="state-card">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading Context Pack…</span>
    </div>

    <!-- NOT FOUND -->
    <div
      v-else-if="state === 'not-found'"
      class="state-card state-card--empty"
    >
      <h2 class="state-card__title">Context Pack not found</h2>
      <p class="text-secondary">
        It may have been deleted, or you don't have access to it.
      </p>
      <RouterLink to="/context-zoo" class="btn btn--primary">
        Back to Context Zoo
      </RouterLink>
    </div>

    <!-- ERROR -->
    <div
      v-else-if="state === 'error'"
      class="banner banner--error"
      role="alert"
    >
      <strong>Could not load this pack.</strong>
      <span>{{ errorMessage }}</span>
      <button class="btn btn--ghost btn--sm" type="button" @click="loadPack">
        Try again
      </button>
    </div>

    <!-- READY -->
    <template v-else-if="pack">
      <!-- Header card -->
      <header class="zoo-detail__header card">
        <div class="zoo-detail__header-text">
          <div class="zoo-detail__title-row">
            <h1 class="zoo-detail__title">{{ pack.title }}</h1>
            <div class="zoo-detail__type-chips" aria-label="Content types">
              <span
                v-for="tag in contentTypes"
                :key="tag"
                class="chip"
                :class="{
                  'chip--success': tag === 'Graph',
                  'chip--warning': tag === 'Vector'
                }"
              >
                {{ tag }}
              </span>
            </div>
          </div>

          <p v-if="pack.description" class="zoo-detail__description">
            {{ pack.description }}
          </p>
          <p v-else class="zoo-detail__description text-muted">
            No description.
          </p>

          <dl class="zoo-detail__meta">
            <div>
              <dt>Source type</dt>
              <dd>
                <span
                  class="chip"
                  :class="sourceChipClass"
                >
                  {{ sourceLabel }}
                </span>
              </dd>
            </div>
            <div v-if="pack.project">
              <dt>Project</dt>
              <dd>
                <RouterLink
                  :to="{
                    name: 'project-detail',
                    params: { id: String(pack.project.id) }
                  }"
                  class="zoo-detail__link"
                >
                  {{ pack.project.name }}
                </RouterLink>
              </dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd :title="formatDateTime(pack.created_at)">
                {{ relativeTime(pack.created_at) }}
              </dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd :title="formatDateTime(pack.updated_at)">
                {{ relativeTime(pack.updated_at) }}
              </dd>
            </div>
            <div>
              <dt>Uses</dt>
              <dd>{{ pack.usage_count || 0 }}</dd>
            </div>
            <div>
              <dt>Last used</dt>
              <dd :title="pack.last_used_at ? formatDateTime(pack.last_used_at) : ''">
                {{ pack.last_used_at ? relativeTime(pack.last_used_at) : 'Never' }}
              </dd>
            </div>
            <div v-if="pack.version != null">
              <dt>Version</dt>
              <dd>v{{ pack.version }}</dd>
            </div>
          </dl>
        </div>

        <div class="zoo-detail__actions">
          <button
            type="button"
            class="btn btn--primary"
            :disabled="using"
            @click="onUseInNewConversation"
          >
            <span v-if="using" class="spinner" aria-hidden="true" />
            <span>{{ using ? 'Starting…' : 'Use in new conversation' }}</span>
          </button>
          <button
            type="button"
            class="btn btn--ghost"
            :disabled="copying"
            @click="onCopySummary"
          >
            {{ copied ? 'Copied!' : copying ? 'Copying…' : 'Copy summary' }}
          </button>
          <RouterLink
            v-if="pack.project_id"
            :to="{
              name: 'project-context-pack',
              params: {
                id: String(pack.project_id),
                packId: String(pack.id)
              }
            }"
            class="btn btn--ghost"
          >
            Edit
          </RouterLink>
          <button
            type="button"
            class="btn btn--danger btn--ghost"
            :disabled="deleting"
            @click="openDeleteConfirm"
          >
            <span v-if="deleting" class="spinner" aria-hidden="true" />
            Delete
          </button>
        </div>
      </header>

      <!-- Summary -->
      <section v-if="pack.summary" class="card">
        <h2 class="card__title card__title--sm">Summary</h2>
        <p class="zoo-detail__summary">{{ pack.summary }}</p>
      </section>

      <!-- Keywords -->
      <section
        v-if="pack.keywords && pack.keywords.length"
        class="card"
      >
        <h2 class="card__title card__title--sm">Keywords</h2>
        <ul class="zoo-detail__keywords" aria-label="Keywords">
          <li
            v-for="(kw, idx) in pack.keywords"
            :key="idx"
            class="chip chip--primary"
          >
            {{ kw }}
          </li>
        </ul>
      </section>

      <!-- Structured content (JSON preview) -->
      <section v-if="hasStructuredContent" class="card">
        <h2 class="card__title card__title--sm">Structured content</h2>
        <p class="text-secondary zoo-detail__hint">
          JSON payload — surfaces the pack's structured representation
          when present alongside the Markdown body.
        </p>
        <pre class="zoo-detail__code">{{ structuredContentPreview }}</pre>
      </section>

      <!-- Body -->
      <section v-if="pack.body" class="card">
        <h2 class="card__title card__title--sm">Body</h2>
        <pre class="zoo-detail__body">{{ pack.body }}</pre>
      </section>

      <!-- Sources -->
      <section class="card">
        <h2 class="card__title card__title--sm">
          Sources
          <span v-if="sources.length" class="zoo-detail__count">
            · {{ sources.length }}
          </span>
        </h2>

        <div v-if="sourcesLoading" class="state-row">
          <span class="spinner" aria-hidden="true" />
          <span class="text-secondary">Loading sources…</span>
        </div>

        <p
          v-else-if="!sources.length"
          class="text-secondary zoo-detail__hint"
        >
          This pack has no recorded provenance rows.
        </p>

        <ul v-else class="zoo-detail__sources">
          <li
            v-for="src in sources"
            :key="src.id"
            class="zoo-detail__source"
          >
            <span
              class="chip zoo-detail__source-chip"
              :class="sourceRowChipClass(src.source_type)"
            >
              {{ sourceTypeLabel(src.source_type) }}
            </span>
            <RouterLink
              v-if="sourceLink(src)"
              :to="sourceLink(src)"
              class="zoo-detail__source-title"
            >
              {{ src.source_title || sourceFallbackTitle(src) }}
            </RouterLink>
            <span v-else class="zoo-detail__source-title">
              {{ src.source_title || sourceFallbackTitle(src) }}
            </span>
            <span
              v-if="src.metadata && metadataSummary(src.metadata)"
              class="zoo-detail__source-meta"
            >
              · {{ metadataSummary(src.metadata) }}
            </span>
          </li>
        </ul>
      </section>
    </template>

    <!-- Project picker (for "Use in new conversation" when pack has no project) -->
    <ConfirmDialog
      :open="projectPickerOpen"
      title="Choose a project"
      confirm-label="Start chat"
      cancel-label="Cancel"
      :busy="using"
      busy-label="Starting…"
      @confirm="onPickerConfirm"
      @cancel="onPickerCancel"
    >
      <template #default>
        <span>
          This pack isn't tied to a project. Choose where to start the new conversation:
        </span>
        <select
          v-model="selectedProjectId"
          class="select zoo-detail__picker-select"
        >
          <option disabled value="">Select a project…</option>
          <option
            v-for="p in projects"
            :key="p.id"
            :value="String(p.id)"
          >
            {{ p.name }}
          </option>
        </select>
      </template>
    </ConfirmDialog>

    <!-- Delete confirm -->
    <ConfirmDialog
      :open="deleteOpen"
      :title="deleteTitle"
      message="This removes the pack and its source references. This action cannot be undone."
      confirm-label="Delete"
      busy-label="Deleting…"
      tone="danger"
      :busy="deleting"
      @confirm="onConfirmDelete"
      @cancel="onCancelDelete"
    />
  </div>
</template>

<script setup>
/**
 * ContextZooDetailView — flat detail page for a single Context Pack.
 *
 * Reached via ``/context-zoo/:contextPackId``. Unlike the legacy
 * ``ContextPackView`` (which requires a project id in the URL), this
 * view works for any pack — including ones whose ``project_id`` is
 * null (note- or attachment-only packs).
 *
 * Shows the full pack (title, description, summary, keywords,
 * structured content, body, sources) and exposes four actions:
 *   - **Use in new conversation**: creates a conversation pre-attached
 *     to this pack; asks the user to pick a project if the pack isn't
 *     tied to one, and also calls the ``/use`` endpoint to bump
 *     usage_count / last_used_at.
 *   - **Copy summary**: copies the pack's ``summary`` (falling back to
 *     ``body`` if summary is empty) to the clipboard.
 *   - **Edit**: redirects to the existing project-scoped edit page so
 *     we don't duplicate the edit UI. Only available when the pack has
 *     a project.
 *   - **Delete**: confirms via the shared ConfirmDialog, then returns
 *     to the Zoo.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import contextPacksApi from '@/api/contextPacks'
import chatApi from '@/api/chat'
import projectsApi from '@/api/projects'
import { useToasts } from '@/stores/toasts'
import { describeApiError } from '@/utils/errors'
import { formatDateTime, relativeTime } from '@/utils/time'
import {
  contentTypesForPack,
  sourceTypeChipVariant,
  sourceTypeLabel
} from '@/utils/contentTypes'

const props = defineProps({
  /** URL param from the router. Arrives as a string. */
  contextPackId: { type: [String, Number], required: true }
})

const router = useRouter()
const toasts = useToasts()

// ---- Core data ----
const state = ref('loading') // 'loading' | 'ready' | 'not-found' | 'error'
const pack = ref(null)
const errorMessage = ref('')

// ---- Sources ----
const sources = ref([])
const sourcesLoading = ref(false)

// ---- Actions ----
const using = ref(false)
const copying = ref(false)
const copied = ref(false)
let copyResetTimer = null

// ---- Delete flow ----
const deleteOpen = ref(false)
const deleting = ref(false)
const deleteTitle = computed(() =>
  pack.value ? `Delete "${pack.value.title}"?` : 'Delete Context Pack?'
)

// ---- Use-in-new-conversation (project picker) flow ----
const projectPickerOpen = ref(false)
const selectedProjectId = ref('')
const projects = ref([])

// ---- Derived ----
const contentTypes = computed(() => contentTypesForPack(pack.value))
const sourceLabel = computed(() => sourceTypeLabel(pack.value?.source_type))
const sourceChipClass = computed(() => {
  const v = sourceTypeChipVariant(pack.value?.source_type)
  return v ? `chip--${v}` : ''
})

const hasStructuredContent = computed(() => {
  const sc = pack.value?.structured_content
  if (sc == null) return false
  if (Array.isArray(sc)) return sc.length > 0
  if (typeof sc === 'object') return Object.keys(sc).length > 0
  return false
})

const structuredContentPreview = computed(() => {
  if (!hasStructuredContent.value) return ''
  try {
    return JSON.stringify(pack.value.structured_content, null, 2)
  } catch (_e) {
    return '[unserializable]'
  }
})

// ---- Lifecycle ----

watch(
  () => props.contextPackId,
  () => {
    loadPack()
    loadSources()
  }
)

onMounted(() => {
  loadPack()
  loadSources()
})

// ---- API ----

async function loadPack() {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const data = await contextPacksApi.get(props.contextPackId)
    if (!data?.context_pack) {
      state.value = 'not-found'
      pack.value = null
      return
    }
    pack.value = data.context_pack
    state.value = 'ready'
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

async function loadSources() {
  sourcesLoading.value = true
  try {
    const data = await contextPacksApi.listSources(props.contextPackId)
    sources.value = Array.isArray(data?.sources) ? data.sources : []
  } catch (_err) {
    // Non-fatal: the page still works without a sources list.
    sources.value = []
  } finally {
    sourcesLoading.value = false
  }
}

async function ensureProjectsLoaded() {
  if (projects.value.length) return
  try {
    const data = await projectsApi.list()
    projects.value = Array.isArray(data?.projects) ? data.projects : []
  } catch (_err) {
    projects.value = []
  }
}

// ---- Actions: Use in new conversation ----

async function onUseInNewConversation() {
  if (!pack.value || using.value) return
  // If the pack is bound to a project, create directly; else ask the
  // user to pick one via the ConfirmDialog-as-picker.
  if (pack.value.project_id) {
    await startNewChatInProject(pack.value.project_id)
    return
  }
  await ensureProjectsLoaded()
  if (!projects.value.length) {
    toasts.push({
      kind: 'error',
      message:
        'You have no projects yet. Create a project first, then use this pack there.'
    })
    return
  }
  selectedProjectId.value = String(projects.value[0].id)
  projectPickerOpen.value = true
}

async function onPickerConfirm() {
  const pid = parseInt(selectedProjectId.value, 10)
  if (!Number.isFinite(pid)) {
    toasts.push({ kind: 'error', message: 'Please pick a project.' })
    return
  }
  await startNewChatInProject(pid)
}

function onPickerCancel() {
  if (using.value) return
  projectPickerOpen.value = false
}

async function startNewChatInProject(projectId) {
  if (!pack.value || using.value) return
  using.value = true
  try {
    const data = await chatApi.createConversation(projectId, {
      context_pack_id: pack.value.id
    })
    const convo = data?.conversation
    // Fire-and-forget usage bump. We don't wait on this because the
    // redirect is the priority; any failure is logged server-side.
    contextPacksApi.registerUsage(pack.value.id).catch(() => {})
    projectPickerOpen.value = false
    toasts.push({
      kind: 'success',
      message: `Started a new chat with "${pack.value.title}" attached.`
    })
    if (convo?.id) {
      router.push({
        name: 'project-chat',
        params: {
          id: String(projectId),
          cid: String(convo.id)
        }
      })
    } else {
      router.push({
        name: 'project-chat',
        params: { id: String(projectId) }
      })
    }
  } catch (err) {
    toasts.push({
      kind: 'error',
      message: describeApiError(err, 'Could not start a new conversation.')
    })
  } finally {
    using.value = false
  }
}

// ---- Actions: Copy summary ----

async function onCopySummary() {
  if (!pack.value || copying.value) return
  copying.value = true
  try {
    const text = (pack.value.summary || pack.value.body || '').trim()
    if (!text) {
      toasts.push({
        kind: 'error',
        message: 'This pack has no summary or body to copy.'
      })
      return
    }
    await navigator.clipboard.writeText(text)
    copied.value = true
    if (copyResetTimer) clearTimeout(copyResetTimer)
    copyResetTimer = setTimeout(() => {
      copied.value = false
    }, 1800)
  } catch (_err) {
    toasts.push({
      kind: 'error',
      message: 'Could not copy to clipboard.'
    })
  } finally {
    copying.value = false
  }
}

// ---- Actions: Delete ----

function openDeleteConfirm() {
  deleteOpen.value = true
}

function onCancelDelete() {
  if (deleting.value) return
  deleteOpen.value = false
}

async function onConfirmDelete() {
  if (!pack.value || deleting.value) return
  deleting.value = true
  try {
    await contextPacksApi.remove(pack.value.id)
    toasts.push({
      kind: 'success',
      message: `Deleted "${pack.value.title}".`
    })
    router.replace({ name: 'context-zoo' })
  } catch (err) {
    toasts.push({
      kind: 'error',
      message: describeApiError(err, 'Could not delete this pack.')
    })
    deleting.value = false
  }
}

// ---- Sources rendering helpers ----

function sourceRowChipClass(type) {
  const v = sourceTypeChipVariant(type)
  return v ? `chip--${v}` : ''
}

function sourceFallbackTitle(src) {
  const type = sourceTypeLabel(src.source_type).toLowerCase()
  const id =
    src.source_id ??
    src.project_id ??
    src.conversation_id ??
    src.note_id ??
    src.attachment_id
  return id != null ? `${type} #${id}` : type
}

function sourceLink(src) {
  switch (src.source_type) {
    case 'project':
      return src.project_id
        ? { name: 'project-detail', params: { id: String(src.project_id) } }
        : null
    case 'conversation':
      return src.conversation_id && src.project_id
        ? {
            name: 'project-chat',
            params: {
              id: String(src.project_id),
              cid: String(src.conversation_id)
            }
          }
        : null
    default:
      // Messages / notes / attachments don't have dedicated routes yet.
      return null
  }
}

function metadataSummary(meta) {
  // Render a terse one-line summary of a source row's metadata to
  // avoid dumping raw JSON in the list. Highlights the two fields
  // users actually read: message_count (for conversation rows) and
  // role (for message rows).
  if (!meta || typeof meta !== 'object') return ''
  if (typeof meta.message_count === 'number') {
    return `${meta.message_count} message${meta.message_count === 1 ? '' : 's'}`
  }
  if (typeof meta.role === 'string') {
    return meta.role
  }
  return ''
}
</script>

<style scoped>
.zoo-detail {
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
  align-self: flex-start;
}

.back-link:hover {
  color: var(--color-text-primary);
}

.state-card {
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.state-card--empty {
  text-align: center;
}

.state-card__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 500;
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

/* ---- Header card ------------------------------------------------- */

.zoo-detail__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  justify-content: space-between;
  align-items: flex-start;
}

.zoo-detail__header-text {
  flex: 1 1 320px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.zoo-detail__title-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.zoo-detail__title {
  font-size: var(--text-2xl);
  font-weight: 500;
  margin: 0;
  word-break: break-word;
  flex: 1 1 auto;
  min-width: 0;
}

.zoo-detail__type-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.zoo-detail__description {
  margin: 0;
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  max-width: 720px;
}

.zoo-detail__meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--space-2) var(--space-4);
  margin: 0;
}

.zoo-detail__meta > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.zoo-detail__meta dt {
  font-size: 10px;
  font-weight: 500;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.zoo-detail__meta dd {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.zoo-detail__link {
  color: var(--color-primary);
  text-decoration: none;
}
.zoo-detail__link:hover {
  text-decoration: underline;
}

.zoo-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: flex-start;
  flex-shrink: 0;
}

/* ---- Body sections ----------------------------------------------- */

.zoo-detail__summary {
  margin: 0;
  font-size: var(--text-base);
  color: var(--color-text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
}

.zoo-detail__keywords {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.zoo-detail__hint {
  font-size: var(--text-sm);
  margin: 0 0 var(--space-2);
}

.zoo-detail__code {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--color-text-primary);
  max-height: 420px;
  overflow: auto;
  white-space: pre;
}

.zoo-detail__body {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--color-text-primary);
  max-height: 640px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---- Sources ------------------------------------------------------ */

.zoo-detail__count {
  font-weight: 400;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.zoo-detail__sources {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.zoo-detail__source {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

.zoo-detail__source-chip {
  font-size: 10px;
  padding: 2px 8px;
  font-weight: 500;
  flex-shrink: 0;
}

.zoo-detail__source-title {
  color: var(--color-text-primary);
  text-decoration: none;
  font-weight: 500;
  flex: 1 1 auto;
  min-width: 0;
  word-break: break-word;
}
.zoo-detail__source-title:hover {
  color: var(--color-primary);
}

.zoo-detail__source-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.state-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

/* ---- Project picker dialog -------------------------------------- */

.zoo-detail__picker-select {
  display: block;
  margin-top: var(--space-3);
  width: 100%;
}
</style>
