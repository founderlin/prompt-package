<template>
  <div class="project-detail">
    <RouterLink to="/projects" class="back-link">
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
      All projects
    </RouterLink>

    <div v-if="state === 'loading'" class="state-card">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading project…</span>
    </div>

    <div v-else-if="state === 'not-found'" class="state-card state-card--empty">
      <h2 class="state-card__title">Project not found</h2>
      <p class="text-secondary">
        It may have been deleted, or you don't have access to it.
      </p>
      <RouterLink to="/projects" class="btn btn--primary">Back to projects</RouterLink>
    </div>

    <div v-else-if="state === 'error'" class="banner banner--error" role="alert">
      <strong>Could not load this project.</strong>
      <span>{{ errorMessage }}</span>
      <button class="btn btn--ghost btn--sm" type="button" @click="loadProject">
        Try again
      </button>
    </div>

    <template v-else-if="project">
      <header class="project-detail__header card">
        <div class="project-detail__header-text">
          <h1 class="project-detail__name">{{ project.name }}</h1>
          <p v-if="project.description" class="project-detail__description">
            {{ project.description }}
          </p>
          <p v-else class="project-detail__description text-muted">
            No description yet.
            <button type="button" class="link-btn" @click="openEdit">Add one</button>.
          </p>
          <dl class="project-detail__meta">
            <div>
              <dt>Created</dt>
              <dd>{{ formatDateTime(project.created_at) || '—' }}</dd>
            </div>
            <div>
              <dt>Last updated</dt>
              <dd>{{ formatDateTime(project.updated_at) || '—' }}</dd>
            </div>
            <div>
              <dt>Project ID</dt>
              <dd><code>#{{ project.id }}</code></dd>
            </div>
          </dl>
        </div>

        <div class="project-detail__actions">
          <RouterLink
            class="btn btn--primary"
            :to="{ name: 'project-chat', params: { id: String(project.id) } }"
          >
            Start chat
          </RouterLink>
          <button class="btn btn--ghost" type="button" @click="openEdit">Edit</button>
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

      <section class="card">
        <header class="section-row">
          <div>
            <h3 class="card__title card__title--sm">Blablas</h3>
            <p class="text-secondary section-row__hint">
              Every chat with the model is saved here automatically.
            </p>
          </div>
          <RouterLink
            class="btn btn--ghost btn--sm"
            :to="{ name: 'project-chat', params: { id: String(project.id) } }"
          >
            New chat
          </RouterLink>
        </header>

        <div v-if="conversationsLoading" class="state-row">
          <span class="spinner" aria-hidden="true" />
          <span class="text-secondary">Loading blablas…</span>
        </div>

        <div
          v-else-if="conversationsError"
          class="banner banner--error"
          role="alert"
        >
          <strong>Could not load blablas.</strong>
          <span>{{ conversationsError }}</span>
          <button
            class="btn btn--ghost btn--sm"
            type="button"
            @click="loadConversations"
          >
            Retry
          </button>
        </div>

        <ul v-else-if="conversations.length" class="conversation-list">
          <li v-for="convo in conversations" :key="convo.id" class="conversation-row">
            <RouterLink
              :to="{
                name: 'project-chat',
                params: { id: String(project.id), cid: String(convo.id) }
              }"
              class="conversation-row__link"
            >
              <div class="conversation-row__main">
                <span class="conversation-row__title">
                  {{ convo.title || 'Untitled blabla' }}
                </span>
                <span class="conversation-row__meta">
                  <span v-if="convo.model">{{ modelLabel(convo.model) }}</span>
                  <span>
                    · {{ convo.message_count || 0 }}
                    {{ (convo.message_count || 0) === 1 ? 'msg' : 'msgs' }}
                  </span>
                  <span v-if="convo.last_message_at">
                    · {{ relativeTime(convo.last_message_at) }}
                  </span>
                  <span v-else-if="convo.created_at">
                    · created {{ relativeTime(convo.created_at) }}
                  </span>
                  <span
                    v-if="convo.summarized_at"
                    class="conversation-row__badge"
                  >
                    Summarized
                  </span>
                </span>
              </div>
              <svg
                class="conversation-row__chevron"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </RouterLink>
          </li>
        </ul>

        <EmptyState
          v-else
          compact
          title="No blablas yet"
          description="Hit Start chat to send your first message. The transcript will be saved here automatically."
        >
          <template #icon>
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M4 6h16v10H8l-4 4z" />
              <path d="M8 11h8M8 8h6" />
            </svg>
          </template>
        </EmptyState>
      </section>

      <!-- Anchor target so external pages (e.g. the wrap-up toast fired
           from ProjectChatView) can deep-link here via `#project-memories`.
           See the focusMemoriesHash() helper + route-hash watcher in this
           file's <script setup>. -->
      <section id="project-memories" class="card">
        <header class="section-row">
          <div>
            <h3 class="card__title card__title--sm">Memories</h3>
            <p class="text-secondary section-row__hint">
              Auto-extracted facts, decisions, todos, and open questions from
              wrapped-up blablas.
            </p>
          </div>
          <button
            class="btn btn--ghost btn--sm"
            type="button"
            :disabled="memoriesLoading"
            @click="loadMemories"
          >
            Refresh
          </button>
        </header>

        <div v-if="memoryDeleteError" class="banner banner--error" role="alert">
          <strong>Could not delete memory.</strong>
          <span>{{ memoryDeleteError }}</span>
        </div>

        <div v-if="memoriesLoading && !memories.length" class="state-row">
          <span class="spinner" aria-hidden="true" />
          <span class="text-secondary">Loading memories…</span>
        </div>

        <div v-else-if="memoriesError" class="banner banner--error" role="alert">
          <strong>Could not load memories.</strong>
          <span>{{ memoriesError }}</span>
          <button
            class="btn btn--ghost btn--sm"
            type="button"
            @click="loadMemories"
          >
            Retry
          </button>
        </div>

        <div v-else-if="memories.length" class="memory-groups">
          <div
            v-for="group in groupedMemories"
            :key="group.kind"
            class="memory-group"
          >
            <h4 class="memory-group__title">
              {{ group.label }}
              <span class="memory-group__count">{{ group.items.length }}</span>
            </h4>
            <ul class="memory-list">
              <li
                v-for="item in group.items"
                :key="item.id"
                class="memory-row"
              >
                <div class="memory-row__main">
                  <p class="memory-row__content">{{ item.content }}</p>
                  <p
                    v-if="item.source_excerpt"
                    class="memory-row__excerpt"
                  >
                    “{{ item.source_excerpt }}”
                  </p>
                  <p class="memory-row__meta">
                    <RouterLink
                      v-if="item.conversation_id"
                      :to="{
                        name: 'project-chat',
                        params: {
                          id: String(project.id),
                          cid: String(item.conversation_id)
                        }
                      }"
                      class="memory-row__link"
                    >
                      <span v-if="item.conversation?.title">
                        From: {{ item.conversation.title }}
                      </span>
                      <span v-else>From blabla #{{ item.conversation_id }}</span>
                    </RouterLink>
                    <span v-if="item.created_at" class="memory-row__time">
                      · {{ relativeTime(item.created_at) }}
                    </span>
                  </p>
                </div>
                <button
                  class="memory-row__delete"
                  type="button"
                  :disabled="removingMemoryId === item.id"
                  :aria-label="`Delete memory ${item.id}`"
                  @click="removeMemory(item)"
                >
                  <span
                    v-if="removingMemoryId === item.id"
                    class="spinner"
                    aria-hidden="true"
                  />
                  <span v-else aria-hidden="true">×</span>
                </button>
              </li>
            </ul>
          </div>
        </div>

        <EmptyState
          v-else
          compact
          title="No memories extracted yet"
          description="Wrap up any blabla in this project to extract decisions, todos, and key facts."
        >
          <template #icon>
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M12 2a7 7 0 0 0-7 7c0 2.5 1.3 4 2 5l1 5h8l1-5c.7-1 2-2.5 2-5a7 7 0 0 0-7-7z" />
              <path d="M9 21h6" />
            </svg>
          </template>
        </EmptyState>
      </section>

      <section class="card">
        <header class="section-row">
          <div>
            <h3 class="card__title card__title--sm">Context Packs</h3>
            <p class="text-secondary section-row__hint">
              A reusable bundle of this project's memories — paste it into a fresh AI chat to bootstrap context.
            </p>
          </div>
          <button
            class="btn btn--primary btn--sm"
            type="button"
            :disabled="generating || !memories.length"
            @click="togglePackForm"
          >
            {{ packFormOpen ? 'Cancel' : 'Generate Context Pack' }}
          </button>
        </header>

        <p
          v-if="!memories.length && !memoriesLoading && !memoriesError"
          class="text-secondary pack-hint"
        >
          Wrap up at least one blabla first — Context Packs are built from this project's memories.
        </p>

        <form
          v-if="packFormOpen"
          class="pack-form"
          @submit.prevent="onGenerate"
        >
          <label class="pack-form__field">
            <span class="pack-form__label">Title (optional)</span>
            <input
              v-model="packTitle"
              type="text"
              class="input"
              placeholder="Defaults to project name + timestamp"
              maxlength="160"
            />
          </label>
          <label class="pack-form__field">
            <span class="pack-form__label">Extra instructions (optional)</span>
            <textarea
              v-model="packInstructions"
              class="textarea"
              rows="3"
              maxlength="1000"
              placeholder="e.g. Focus on backend decisions, write as a system prompt"
            />
            <span class="pack-form__hint">
              The model will follow this on top of the standard pack format.
            </span>
          </label>
          <div class="pack-form__actions">
            <span v-if="generateError" class="pack-form__error">
              {{ generateError }}
            </span>
            <span v-else class="pack-form__hint">
              Uses {{ memories.length }} {{ memories.length === 1 ? 'memory' : 'memories' }} from this project.
            </span>
            <button
              type="submit"
              class="btn btn--primary"
              :disabled="generating"
            >
              <span v-if="generating" class="spinner" aria-hidden="true" />
              {{ generating ? 'Generating…' : 'Generate' }}
            </button>
          </div>
        </form>

        <div v-if="packsLoading && !packs.length" class="state-row">
          <span class="spinner" aria-hidden="true" />
          <span class="text-secondary">Loading Context Packs…</span>
        </div>

        <div v-else-if="packsError" class="banner banner--error" role="alert">
          <strong>Could not load Context Packs.</strong>
          <span>{{ packsError }}</span>
          <button class="btn btn--ghost btn--sm" type="button" @click="loadPacks">
            Retry
          </button>
        </div>

        <ul v-else-if="packs.length" class="pack-list">
          <li v-for="pack in packs" :key="pack.id" class="pack-row">
            <RouterLink
              :to="{
                name: 'project-context-pack',
                params: {
                  id: String(project.id),
                  packId: String(pack.id)
                }
              }"
              class="pack-row__link"
            >
              <div class="pack-row__main">
                <span class="pack-row__title">{{ pack.title }}</span>
                <p
                  v-if="pack.body_preview"
                  class="pack-row__preview"
                >
                  {{ pack.body_preview }}
                </p>
                <span class="pack-row__meta">
                  <span v-if="pack.model">{{ modelLabel(pack.model) }}</span>
                  <span>
                    · {{ pack.memory_count || 0 }}
                    {{ (pack.memory_count || 0) === 1 ? 'memory' : 'memories' }}
                  </span>
                  <span v-if="pack.created_at">· {{ relativeTime(pack.created_at) }}</span>
                </span>
              </div>
              <div class="pack-row__actions">
                <button
                  class="pack-row__copy"
                  type="button"
                  :title="copiedPackId === pack.id ? 'Copied!' : 'Copy pack'"
                  @click.prevent.stop="copyPack(pack)"
                >
                  <span v-if="copiedPackId === pack.id">Copied</span>
                  <span v-else>Copy</span>
                </button>
                <svg
                  class="pack-row__chevron"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </div>
            </RouterLink>
          </li>
        </ul>

        <EmptyState
          v-else
          compact
          title="No Context Packs yet"
          description="Click Generate Context Pack to turn this project's memories into a reusable Markdown briefing."
        >
          <template #icon>
            <svg
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M12 3 3 7.5v9L12 21l9-4.5v-9L12 3Z" />
              <path d="m3 7.5 9 4.5 9-4.5" />
              <path d="M12 12v9" />
            </svg>
          </template>
        </EmptyState>
      </section>

      <ProjectFormDialog
        :open="dialogOpen"
        :project="project"
        @close="closeDialog"
        @updated="onUpdated"
      />
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'
import ProjectFormDialog from '@/components/projects/ProjectFormDialog.vue'
import projectsApi from '@/api/projects'
import chatApi from '@/api/chat'
import memoriesApi from '@/api/memories'
import contextPacksApi from '@/api/contextPacks'
import { describeApiError } from '@/utils/errors'
import { formatDateTime, relativeTime } from '@/utils/time'
import { modelLabel } from '@/constants/models'

const MEMORY_KIND_LABELS = {
  decision: 'Decisions',
  todo: 'Todos',
  fact: 'Facts',
  question: 'Open questions'
}

const props = defineProps({
  id: { type: [String, Number], required: true }
})

const route = useRoute()
const router = useRouter()

const state = ref('loading') // 'loading' | 'ready' | 'not-found' | 'error'
const project = ref(null)
const errorMessage = ref('')
const deleting = ref(false)
const dialogOpen = ref(false)

const conversations = ref([])
const conversationsLoading = ref(false)
const conversationsError = ref('')

const memories = ref([])
const memoriesLoading = ref(false)
const memoriesError = ref('')
const removingMemoryId = ref(null)
const memoryDeleteError = ref('')

const packs = ref([])
const packsLoading = ref(false)
const packsError = ref('')
const packFormOpen = ref(false)
const packTitle = ref('')
const packInstructions = ref('')
const generating = ref(false)
const generateError = ref('')
const copiedPackId = ref(null)
let copiedTimer = null

const groupedMemories = computed(() => {
  const order = ['decision', 'todo', 'fact', 'question']
  const groups = order
    .map((kind) => ({
      kind,
      label: MEMORY_KIND_LABELS[kind] || kind,
      items: memories.value.filter((m) => m.kind === kind)
    }))
    .filter((g) => g.items.length > 0)
  const known = new Set(order)
  const others = memories.value.filter((m) => !known.has(m.kind))
  if (others.length) {
    groups.push({ kind: 'other', label: 'Other', items: others })
  }
  return groups
})

async function loadProject() {
  state.value = 'loading'
  errorMessage.value = ''
  memoryDeleteError.value = ''
  try {
    const data = await projectsApi.get(props.id)
    project.value = data?.project || null
    state.value = project.value ? 'ready' : 'not-found'
    if (state.value === 'ready') {
      loadConversations()
      loadMemories()
      loadPacks()
    }
  } catch (err) {
    if (err?.response?.status === 404) {
      state.value = 'not-found'
      project.value = null
    } else {
      state.value = 'error'
      errorMessage.value = describeApiError(err, 'Could not load this project.')
    }
  }
}

async function loadConversations() {
  if (!project.value) return
  conversationsLoading.value = true
  conversationsError.value = ''
  try {
    const data = await chatApi.listConversations(project.value.id)
    conversations.value = Array.isArray(data?.conversations)
      ? data.conversations
      : []
  } catch (err) {
    conversationsError.value = describeApiError(
      err,
      'Could not load blablas.'
    )
  } finally {
    conversationsLoading.value = false
  }
}

async function loadMemories() {
  if (!project.value) return
  memoriesLoading.value = true
  memoriesError.value = ''
  try {
    const data = await memoriesApi.listForProject(project.value.id)
    memories.value = Array.isArray(data?.memories) ? data.memories : []
  } catch (err) {
    memoriesError.value = describeApiError(err, 'Could not load memories.')
  } finally {
    memoriesLoading.value = false
  }
}

async function removeMemory(memory) {
  if (!memory) return
  const ok = window.confirm('Remove this memory? This cannot be undone.')
  if (!ok) return
  removingMemoryId.value = memory.id
  memoryDeleteError.value = ''
  try {
    await memoriesApi.remove(memory.id)
    memories.value = memories.value.filter((m) => m.id !== memory.id)
  } catch (err) {
    memoryDeleteError.value = describeApiError(err, 'Could not delete this memory.')
  } finally {
    removingMemoryId.value = null
  }
}

async function loadPacks() {
  if (!project.value) return
  packsLoading.value = true
  packsError.value = ''
  try {
    const data = await contextPacksApi.listForProject(project.value.id)
    packs.value = Array.isArray(data?.context_packs) ? data.context_packs : []
  } catch (err) {
    packsError.value = describeApiError(err, 'Could not load Context Packs.')
  } finally {
    packsLoading.value = false
  }
}

function togglePackForm() {
  if (packFormOpen.value) {
    packFormOpen.value = false
    generateError.value = ''
    return
  }
  packFormOpen.value = true
  packTitle.value = ''
  packInstructions.value = ''
  generateError.value = ''
}

async function onGenerate() {
  if (!project.value || generating.value) return
  generating.value = true
  generateError.value = ''
  try {
    const data = await contextPacksApi.generate(project.value.id, {
      title: packTitle.value.trim() || undefined,
      instructions: packInstructions.value.trim() || undefined
    })
    const created = data?.context_pack
    if (created) {
      packs.value = [shapePackForList(created), ...packs.value]
      packFormOpen.value = false
      packTitle.value = ''
      packInstructions.value = ''
      router.push({
        name: 'project-context-pack',
        params: {
          id: String(project.value.id),
          packId: String(created.id)
        }
      })
    }
  } catch (err) {
    generateError.value = describeApiError(err, 'Could not generate the pack.')
  } finally {
    generating.value = false
  }
}

function shapePackForList(pack) {
  const body = pack?.body || ''
  const trimmed = body.trim()
  const preview = trimmed.length > 240
    ? trimmed.slice(0, 239).trimEnd() + '…'
    : trimmed
  return {
    ...pack,
    body_preview: preview
  }
}

async function copyPack(pack) {
  if (!pack) return
  try {
    let body = pack.body
    if (typeof body !== 'string' || !body) {
      const data = await contextPacksApi.get(pack.id)
      body = data?.context_pack?.body || ''
    }
    await navigator.clipboard.writeText(body || '')
    copiedPackId.value = pack.id
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => {
      copiedPackId.value = null
    }, 1800)
  } catch (_e) {
    window.alert('Could not copy to clipboard.')
  }
}

function openEdit() {
  dialogOpen.value = true
}

function closeDialog() {
  dialogOpen.value = false
}

function onUpdated(updated) {
  project.value = updated
  closeDialog()
}

async function onDelete() {
  if (!project.value) return
  const ok = window.confirm(
    `Delete "${project.value.name}"? This will remove the project and (later) its blablas and Context Packs.`
  )
  if (!ok) return
  deleting.value = true
  try {
    await projectsApi.remove(project.value.id)
    router.replace({ name: 'projects' })
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not delete the project.')
    state.value = 'error'
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  await loadProject()
  // Honor `#project-memories` deep-links (fired e.g. by the wrap-up toast
  // from ProjectChatView). We do this *after* loadProject resolves so the
  // target element is in the DOM by the time we call scrollIntoView.
  focusHash(route.hash)
})

watch(
  () => route.params.id,
  (next, prev) => {
    if (next && next !== prev) loadProject()
  }
)

// If the user is already on this page and the hash changes (e.g. same
// route, different anchor) scroll to the new target without a reload.
watch(
  () => route.hash,
  (next) => focusHash(next)
)

// Scroll a hash target into view. No-ops for unknown / empty hashes.
// Uses nextTick so v-if-gated sections (like the memories list once it
// finishes loading) are rendered before we look them up.
async function focusHash(hash) {
  if (!hash) return
  const id = String(hash).replace(/^#/, '')
  if (!id) return
  await nextTick()
  const el = document.getElementById(id)
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
</script>

<style scoped>
.project-detail {
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

.project-detail__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  justify-content: space-between;
  align-items: flex-start;
}

.project-detail__header-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.project-detail__name {
  margin: 0;
  font-size: var(--text-2xl, 22px);
  font-weight: 500;
  word-break: break-word;
}

.project-detail__description {
  margin: 0;
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.text-muted {
  color: var(--color-text-muted);
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

.project-detail__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin: var(--space-2) 0 0;
}

.project-detail__meta div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.project-detail__meta dt {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  margin: 0;
}

.project-detail__meta dd {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.project-detail__meta code {
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xs, 4px);
  padding: 1px 6px;
  font-size: var(--text-xs);
}

.project-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.section-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.section-row__hint {
  margin: 4px 0 0;
  font-size: var(--text-sm);
}

.state-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.conversation-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.conversation-row__link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  justify-content: space-between;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  text-decoration: none;
  color: inherit;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.conversation-row__link:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-border);
}

.conversation-row__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.conversation-row__title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conversation-row__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.conversation-row__chevron {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.conversation-row__badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.memory-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.memory-group__title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.memory-group__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0;
  text-transform: none;
}

.memory-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.memory-row {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.memory-row:hover {
  border-color: rgba(26, 115, 232, 0.25);
  background: var(--color-surface-hover);
}

.memory-row__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.memory-row__content {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  line-height: 1.5;
}

.memory-row__excerpt {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-style: italic;
  line-height: 1.45;
  white-space: pre-wrap;
}

.memory-row__meta {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.memory-row__link {
  color: var(--color-primary);
  text-decoration: none;
}

.memory-row__link:hover {
  text-decoration: underline;
}

.memory-row__time {
  color: var(--color-text-muted);
}

.memory-row__delete {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 999px;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--color-text-muted);
  font-size: 18px;
  line-height: 1;
  flex-shrink: 0;
  transition: background-color 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}

.memory-row__delete:hover:not(:disabled) {
  background: var(--color-error-soft);
  color: var(--color-error);
  border-color: rgba(217, 48, 37, 0.35);
}

.memory-row__delete:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.pack-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
}

.pack-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  margin-bottom: var(--space-3);
}

.pack-form__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pack-form__label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.pack-form__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.pack-form__error {
  font-size: var(--text-xs);
  color: var(--color-error);
  flex: 1;
}

.pack-form__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
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
  min-height: 64px;
  line-height: 1.5;
}

.pack-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.pack-row__link {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
  justify-content: space-between;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  text-decoration: none;
  color: inherit;
  background: var(--color-surface);
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.pack-row__link:hover {
  background: var(--color-surface-hover);
  border-color: rgba(26, 115, 232, 0.35);
}

.pack-row__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pack-row__title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-primary);
  word-break: break-word;
}

.pack-row__preview {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}

.pack-row__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pack-row__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

.pack-row__copy {
  font-size: var(--text-xs);
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}

.pack-row__copy:hover {
  background: var(--color-primary-soft);
  border-color: rgba(26, 115, 232, 0.45);
  color: var(--color-primary);
}

.pack-row__chevron {
  color: var(--color-text-muted);
  margin-top: 4px;
}

@media (max-width: 720px) {
  .project-detail__header {
    flex-direction: column;
  }
  .project-detail__actions {
    width: 100%;
  }
  .project-detail__actions .btn {
    flex: 1;
  }
}
</style>
