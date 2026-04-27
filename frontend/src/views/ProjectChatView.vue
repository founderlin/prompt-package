<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import MessageList from '@/components/chat/MessageList.vue'
import ModelPicker from '@/components/chat/ModelPicker.vue'
import chatApi from '@/api/chat'
import contextPacksApi from '@/api/contextPacks'
import memoriesApi from '@/api/memories'
import modelSelectionsApi from '@/api/modelSelections'
import projectsApi from '@/api/projects'
import { useAuth } from '@/stores/auth'
import { describeApiError } from '@/utils/errors'
import { relativeTime } from '@/utils/time'
import {
  DEFAULT_MODEL_ID,
  DEFAULT_PROVIDER,
  findModelOption,
  modelLabel,
  providerLabel
} from '@/constants/models'

const MEMORY_KIND_LABELS = {
  fact: 'Fact',
  decision: 'Decision',
  todo: 'Todo',
  question: 'Question'
}

function memoryKindLabel(kind) {
  return MEMORY_KIND_LABELS[kind] || 'Note'
}

const props = defineProps({
  id: { type: [String, Number], required: true },
  cid: { type: [String, Number], default: null }
})

const route = useRoute()
const router = useRouter()
const auth = useAuth()

const state = ref('loading')
const errorMessage = ref('')
const project = ref(null)
const conversation = ref(null)
const messages = ref([])
const sending = ref(false)
const sendError = ref('')
const composer = ref(null)

const conversations = ref([])
const conversationsLoading = ref(false)
const creatingNew = ref(false)

const summarizing = ref(false)
const summarizeError = ref('')
const summarizeBanner = ref('')
const memoriesList = ref([])
const memoriesOpen = ref(false)

// R13: Context Pack picker (Prompt Plus)
const packPickerOpen = ref(false)
const availablePacks = ref([])
const packsLoading = ref(false)
const packPickerError = ref('')
const packPickerScope = ref('project') // 'project' | 'all'
const packPickerQuery = ref('')
const bindingPackId = ref(null)
const detachingPack = ref(false)

const highlightId = ref(null)
let highlightTimer = null

// User's curated list of models (per provider) — loaded from /api/settings/models.
// Shape: [{ provider, model_id, label }, ...]
const userModels = ref([])
const userModelsLoaded = ref(false)

const selectedModel = ref(DEFAULT_MODEL_ID)
const selectedProvider = ref(DEFAULT_PROVIDER)

const projectIdNum = computed(() => Number(props.id))
const conversationIdNum = computed(() => (props.cid ? Number(props.cid) : null))

const providersConfigured = computed(() => {
  const u = auth.user.value
  if (u?.providers && typeof u.providers === 'object') return u.providers
  // Pre-R14 fallback shape.
  return {
    openrouter: !!u?.has_openrouter_api_key,
    deepseek: false,
    openai: false
  }
})

const hasKeyForSelectedProvider = computed(
  () => Boolean(providersConfigured.value[selectedProvider.value])
)

const hasAnyProviderKey = computed(() =>
  Object.values(providersConfigured.value).some(Boolean)
)

const headerTitle = computed(() => {
  if (conversation.value?.title) return conversation.value.title
  return 'New conversation'
})

const headerSubtitle = computed(() => {
  if (!project.value) return ''
  return project.value.name
})

const composerDisabled = computed(
  () => state.value !== 'ready' || !hasKeyForSelectedProvider.value
)

const composerPlaceholder = computed(() => {
  if (!hasKeyForSelectedProvider.value) {
    return `Add your ${providerLabel(selectedProvider.value)} API key in Settings to start chatting…`
  }
  return 'Type your message… (Enter to send, Shift+Enter for newline)'
})

async function bootstrap() {
  state.value = 'loading'
  errorMessage.value = ''
  summarizeError.value = ''
  summarizeBanner.value = ''
  memoriesList.value = []
  memoriesOpen.value = false

  // Ensure we have the user's curated model list up-front; the picker
  // and the "what model should we use by default" logic both depend on it.
  if (!userModelsLoaded.value) {
    await loadUserModels()
  }

  try {
    const projectData = await projectsApi.get(projectIdNum.value)
    project.value = projectData?.project || null
    if (!project.value) {
      state.value = 'not-found'
      return
    }
  } catch (err) {
    if (err?.response?.status === 404) {
      state.value = 'not-found'
    } else {
      state.value = 'error'
      errorMessage.value = describeApiError(err, 'Could not load this project.')
    }
    return
  }

  // Sidebar conversations are loaded in parallel with the active conversation.
  loadConversations()

  // If we're about to open a *new* conversation (no cid in the URL),
  // pre-seed the picker with the user's first enabled model so the very
  // first turn doesn't silently go to the hard-coded gpt-4o-mini default.
  if (!conversationIdNum.value) {
    const fallback = pickDefaultSelection()
    selectedModel.value = fallback.model_id
    selectedProvider.value = fallback.provider
  }

  try {
    if (conversationIdNum.value) {
      const data = await chatApi.getConversation(conversationIdNum.value)
      const convo = data?.conversation
      if (!convo || convo.project_id !== projectIdNum.value) {
        state.value = 'not-found'
        return
      }
      conversation.value = convo
      messages.value = convo.messages || []
      applyConversationModel(convo.model, convo.provider)
      loadConversationMemories()
    } else {
      const data = await chatApi.createConversation(projectIdNum.value, {
        model: selectedModel.value,
        provider: selectedProvider.value
      })
      const convo = data?.conversation
      conversation.value = convo
      messages.value = convo?.messages || []
      applyConversationModel(convo?.model, convo?.provider)
      router.replace({
        name: 'project-chat',
        params: { id: String(projectIdNum.value), cid: String(convo.id) }
      })
    }
    state.value = 'ready'
    nextTick(() => composer.value?.focus())
    focusHashTarget()
  } catch (err) {
    if (err?.response?.status === 404) {
      state.value = 'not-found'
    } else {
      state.value = 'error'
      errorMessage.value = describeApiError(err, 'Could not load this conversation.')
    }
  }
}

async function loadConversationMemories() {
  if (!conversation.value) return
  try {
    const data = await memoriesApi.listForConversation(conversation.value.id)
    memoriesList.value = Array.isArray(data?.memories) ? data.memories : []
  } catch (_e) {
    memoriesList.value = []
  }
}

function parseHashMessageId(hash) {
  if (!hash) return null
  const match = String(hash).match(/^#?msg-(\d+)$/)
  if (!match) return null
  const n = Number(match[1])
  return Number.isNaN(n) ? null : n
}

async function focusHashTarget() {
  const targetId = parseHashMessageId(route.hash)
  if (!targetId) return
  if (!messages.value.some((m) => Number(m.id) === targetId)) return
  await nextTick()
  const el = document.getElementById(`msg-${targetId}`)
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  highlightId.value = targetId
  if (highlightTimer) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => {
    highlightId.value = null
    highlightTimer = null
  }, 1800)
}

async function loadConversations() {
  if (!project.value) return
  conversationsLoading.value = true
  try {
    const data = await chatApi.listConversations(project.value.id)
    conversations.value = Array.isArray(data?.conversations)
      ? data.conversations
      : []
  } catch (_e) {
    // Sidebar failure is non-fatal — keep whatever we already showed.
  } finally {
    conversationsLoading.value = false
  }
}

function applyConversationModel(modelId, providerId) {
  // Prefer what the conversation itself recorded. If neither is known,
  // fall back to the user's first enabled model (or the built-in default).
  if (modelId) {
    selectedModel.value = modelId
    selectedProvider.value = providerId || inferProvider(modelId)
    return
  }
  const fallback = pickDefaultSelection()
  selectedModel.value = fallback.model_id
  selectedProvider.value = fallback.provider
}

function inferProvider(modelId) {
  // 1) Exact match in user's curated list wins.
  const inUser = userModels.value.find((m) => m.model_id === modelId)
  if (inUser) return inUser.provider
  // 2) Try the curated catalogue.
  const preset = findModelOption(modelId)
  if (preset?.provider) return preset.provider
  return DEFAULT_PROVIDER
}

function pickDefaultSelection() {
  // Prefer a user-configured model whose provider has a working key.
  const enabledProviders = providersConfigured.value
  const configuredPick = userModels.value.find(
    (m) => enabledProviders[m.provider]
  )
  if (configuredPick) {
    return {
      provider: configuredPick.provider,
      model_id: configuredPick.model_id
    }
  }
  // Otherwise, any user-configured model, even if key is missing (UI
  // will nag to add the key).
  if (userModels.value.length) {
    return {
      provider: userModels.value[0].provider,
      model_id: userModels.value[0].model_id
    }
  }
  // Last resort: built-in default so chat never 500s on a fresh install.
  return { provider: DEFAULT_PROVIDER, model_id: DEFAULT_MODEL_ID }
}

async function loadUserModels() {
  try {
    const data = await modelSelectionsApi.list()
    const rows = Array.isArray(data?.models) ? data.models : []
    userModels.value = rows
  } catch (_err) {
    userModels.value = []
  } finally {
    userModelsLoaded.value = true
  }
}

function onModelPicked({ provider, modelId }) {
  selectedProvider.value = provider
  selectedModel.value = modelId
}

async function handleSubmit(content) {
  if (!conversation.value) return
  if (!hasKeyForSelectedProvider.value) {
    sendError.value = `Add your ${providerLabel(selectedProvider.value)} API key in Settings before chatting.`
    return
  }
  const modelId = (selectedModel.value || DEFAULT_MODEL_ID).trim()
  const providerId = selectedProvider.value || DEFAULT_PROVIDER
  if (!modelId) {
    sendError.value = 'Choose a model first.'
    return
  }

  sendError.value = ''
  sending.value = true

  const tempUserMsg = {
    _tempId: `tmp-user-${Date.now()}`,
    role: 'user',
    content,
    model: modelId,
    provider: providerId,
    created_at: new Date().toISOString()
  }
  messages.value = [...messages.value, tempUserMsg]
  composer.value?.reset()

  try {
    const data = await chatApi.sendMessage(conversation.value.id, {
      content,
      model: modelId,
      provider: providerId
    })
    messages.value = messages.value.filter((m) => m !== tempUserMsg)
    if (data?.user_message) messages.value.push(data.user_message)
    if (data?.assistant_message) messages.value.push(data.assistant_message)
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
      applyConversationModel(
        data.conversation.model,
        data.conversation.provider
      )
    }
    loadConversations()
  } catch (err) {
    sendError.value = describeApiError(
      err,
      'Could not get a reply from the model.'
    )
    try {
      const refreshed = await chatApi.listMessages(conversation.value.id)
      if (Array.isArray(refreshed?.messages)) {
        messages.value = refreshed.messages
      }
    } catch (_e) {
      messages.value = messages.value.filter((m) => m !== tempUserMsg)
    }
    loadConversations()
  } finally {
    sending.value = false
    nextTick(() => composer.value?.focus())
  }
}

async function startNewConversation() {
  if (creatingNew.value || !project.value) return
  creatingNew.value = true
  sendError.value = ''
  try {
    const data = await chatApi.createConversation(project.value.id, {
      model: selectedModel.value || DEFAULT_MODEL_ID,
      provider: selectedProvider.value || DEFAULT_PROVIDER
    })
    const convo = data?.conversation
    if (!convo) return
    await router.push({
      name: 'project-chat',
      params: { id: String(project.value.id), cid: String(convo.id) }
    })
  } catch (err) {
    sendError.value = describeApiError(
      err,
      'Could not create a new conversation.'
    )
  } finally {
    creatingNew.value = false
  }
}

const realMessageCount = computed(
  () => messages.value.filter((m) => m.role === 'user' || m.role === 'assistant').length
)

const canSummarize = computed(
  () =>
    state.value === 'ready' &&
    hasAnyProviderKey.value &&
    realMessageCount.value >= 2
)

const groupedMemories = computed(() => {
  const order = ['decision', 'todo', 'fact', 'question']
  const groups = order
    .map((kind) => ({
      kind,
      label: memoryKindLabel(kind),
      items: memoriesList.value.filter((m) => m.kind === kind)
    }))
    .filter((g) => g.items.length > 0)
  const knownKinds = new Set(order)
  const otherItems = memoriesList.value.filter((m) => !knownKinds.has(m.kind))
  if (otherItems.length) {
    groups.push({ kind: 'other', label: 'Other', items: otherItems })
  }
  return groups
})

async function handleWrapUp() {
  if (!conversation.value || summarizing.value) return
  if (realMessageCount.value < 2) {
    summarizeError.value =
      'Send at least one user/assistant exchange before wrapping up.'
    return
  }
  summarizing.value = true
  summarizeError.value = ''
  summarizeBanner.value = ''
  try {
    const data = await chatApi.summarizeConversation(conversation.value.id, {
      model: selectedModel.value || DEFAULT_MODEL_ID
    })
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
    }
    const items = Array.isArray(data?.memories) ? data.memories : []
    memoriesList.value = items
    memoriesOpen.value = items.length > 0
    summarizeBanner.value = items.length
      ? `Wrap-up complete · ${items.length} ${items.length === 1 ? 'memory' : 'memories'} saved.`
      : 'Wrap-up complete, but the model did not extract any memories.'
    loadConversations()
  } catch (err) {
    summarizeError.value = describeApiError(
      err,
      'Could not summarize this conversation.'
    )
  } finally {
    summarizing.value = false
  }
}

// ---- R13: Context Pack picker ----
const attachedPack = computed(() => conversation.value?.context_pack || null)

const filteredPacks = computed(() => {
  const q = packPickerQuery.value.trim().toLowerCase()
  let list = availablePacks.value
  if (packPickerScope.value === 'project') {
    list = list.filter((p) => p.project_id === projectIdNum.value)
  }
  if (q) {
    list = list.filter((p) =>
      (p.title || '').toLowerCase().includes(q) ||
      (p.body_preview || '').toLowerCase().includes(q)
    )
  }
  return list
})

async function loadAvailablePacks() {
  packsLoading.value = true
  packPickerError.value = ''
  try {
    // Fetch the project's packs first (with body_preview); then merge with
    // recent cross-project packs so cross-project reuse "just works".
    const [projectData, recentData] = await Promise.all([
      contextPacksApi.listForProject(projectIdNum.value).catch(() => null),
      contextPacksApi.listRecent({ limit: 50 }).catch(() => null)
    ])
    const byId = new Map()
    const ingest = (rows) => {
      if (!Array.isArray(rows)) return
      for (const p of rows) {
        if (!p?.id) continue
        // Prefer the entry with a body_preview if both sources have it.
        const existing = byId.get(p.id)
        if (!existing || (!existing.body_preview && p.body_preview)) {
          byId.set(p.id, p)
        }
      }
    }
    ingest(projectData?.context_packs)
    ingest(recentData?.context_packs)
    availablePacks.value = Array.from(byId.values()).sort((a, b) => {
      // Project packs first, then by recency.
      const aMine = a.project_id === projectIdNum.value ? 0 : 1
      const bMine = b.project_id === projectIdNum.value ? 0 : 1
      if (aMine !== bMine) return aMine - bMine
      const ad = new Date(a.created_at || 0).getTime()
      const bd = new Date(b.created_at || 0).getTime()
      return bd - ad
    })
  } catch (err) {
    packPickerError.value = describeApiError(err, 'Could not load Context Packs.')
    availablePacks.value = []
  } finally {
    packsLoading.value = false
  }
}

function openPackPicker() {
  packPickerOpen.value = true
  packPickerError.value = ''
  packPickerQuery.value = ''
  // Default to project scope unless we already know nothing exists there.
  packPickerScope.value = 'project'
  if (availablePacks.value.length === 0) loadAvailablePacks()
}

function closePackPicker() {
  packPickerOpen.value = false
  bindingPackId.value = null
}

async function selectPack(packId) {
  if (!conversation.value || bindingPackId.value) return
  bindingPackId.value = packId
  try {
    const data = await chatApi.updateConversation(conversation.value.id, {
      context_pack_id: packId
    })
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
    }
    closePackPicker()
  } catch (err) {
    packPickerError.value = describeApiError(err, 'Could not attach this pack.')
  } finally {
    bindingPackId.value = null
  }
}

async function clearAttachedPack() {
  if (!conversation.value || !attachedPack.value) return
  detachingPack.value = true
  try {
    const data = await chatApi.updateConversation(conversation.value.id, {
      context_pack_id: null
    })
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
    }
  } catch (err) {
    sendError.value = describeApiError(err, 'Could not remove the pack.')
  } finally {
    detachingPack.value = false
  }
}

async function handleDeleteConversation() {
  if (!conversation.value) return
  const ok = window.confirm(
    'Delete this conversation? This cannot be undone.'
  )
  if (!ok) return
  try {
    const deletedId = conversation.value.id
    await chatApi.deleteConversation(deletedId)

    const remaining = conversations.value.filter((c) => c.id !== deletedId)
    conversations.value = remaining

    if (remaining.length) {
      router.replace({
        name: 'project-chat',
        params: {
          id: String(projectIdNum.value),
          cid: String(remaining[0].id)
        }
      })
    } else {
      router.replace({
        name: 'project-detail',
        params: { id: String(projectIdNum.value) }
      })
    }
  } catch (err) {
    sendError.value = describeApiError(err, 'Could not delete the conversation.')
  }
}

onMounted(bootstrap)

watch(
  () => [route.params.id, route.params.cid],
  ([nextId, nextCid], [prevId, prevCid]) => {
    if (nextId !== prevId || nextCid !== prevCid) {
      bootstrap()
    }
  }
)

watch(
  () => route.hash,
  (next, prev) => {
    if (next !== prev && state.value === 'ready') {
      focusHashTarget()
    }
  }
)

onBeforeUnmount(() => {
  if (highlightTimer) {
    clearTimeout(highlightTimer)
    highlightTimer = null
  }
})
</script>

<template>
  <div class="chat-view">
    <RouterLink
      :to="{ name: 'project-detail', params: { id: String(projectIdNum) } }"
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
      <span v-if="project">Back to {{ project.name }}</span>
      <span v-else>Back to project</span>
    </RouterLink>

    <div v-if="state === 'loading'" class="state-card">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading conversation…</span>
    </div>

    <div v-else-if="state === 'not-found'" class="state-card state-card--empty">
      <h2 class="state-card__title">Conversation not found</h2>
      <p class="text-secondary">
        It may have been deleted, or you don't have access to it.
      </p>
      <RouterLink
        :to="{ name: 'project-detail', params: { id: String(projectIdNum) } }"
        class="btn btn--primary"
      >
        Back to project
      </RouterLink>
    </div>

    <div v-else-if="state === 'error'" class="banner banner--error" role="alert">
      <strong>Could not load this conversation.</strong>
      <span>{{ errorMessage }}</span>
      <button class="btn btn--ghost btn--sm" type="button" @click="bootstrap">
        Try again
      </button>
    </div>

    <div v-else class="chat-layout">
      <aside class="chat-sidebar card">
        <header class="chat-sidebar__header">
          <div>
            <p class="chat-sidebar__breadcrumb">{{ project?.name }}</p>
            <h2 class="chat-sidebar__title">Conversations</h2>
          </div>
          <button
            class="btn btn--primary btn--sm"
            type="button"
            :disabled="creatingNew"
            @click="startNewConversation"
          >
            <span v-if="creatingNew" class="spinner" aria-hidden="true" />
            <span>New</span>
          </button>
        </header>

        <div v-if="conversationsLoading && !conversations.length" class="chat-sidebar__loading">
          <span class="spinner" aria-hidden="true" />
          <span>Loading…</span>
        </div>

        <ul v-else-if="conversations.length" class="chat-sidebar__list">
          <li v-for="convo in conversations" :key="convo.id">
            <RouterLink
              :to="{
                name: 'project-chat',
                params: { id: String(projectIdNum), cid: String(convo.id) }
              }"
              class="chat-sidebar__item"
              :class="{
                'chat-sidebar__item--active':
                  conversation && conversation.id === convo.id
              }"
            >
              <span class="chat-sidebar__item-title">
                {{ convo.title || 'New conversation' }}
              </span>
              <span class="chat-sidebar__item-meta">
                <span v-if="convo.model">
                  {{ modelLabel(convo.model, convo.provider) }}
                </span>
                <span v-if="convo.message_count != null">
                  · {{ convo.message_count }} {{ convo.message_count === 1 ? 'msg' : 'msgs' }}
                </span>
                <span v-if="convo.last_message_at">
                  · {{ relativeTime(convo.last_message_at) }}
                </span>
                <span v-else-if="convo.created_at">
                  · {{ relativeTime(convo.created_at) }}
                </span>
                <span v-if="convo.summarized_at" class="chat-sidebar__badge">
                  Summarized
                </span>
              </span>
            </RouterLink>
          </li>
        </ul>

        <p v-else class="chat-sidebar__empty">No conversations yet.</p>
      </aside>

      <section class="chat-shell card">
        <header class="chat-header">
          <div class="chat-header__title-block">
            <p class="chat-header__breadcrumb">{{ headerSubtitle }}</p>
            <h1 class="chat-header__title">{{ headerTitle }}</h1>
          </div>
          <div class="chat-header__controls">
            <div class="prompt-plus" :class="{ 'prompt-plus--active': attachedPack }">
              <span class="prompt-plus__label">Prompt+</span>
              <button
                v-if="attachedPack"
                type="button"
                class="prompt-plus__chip"
                :title="`Attached Context Pack: ${attachedPack.title}`"
                :disabled="sending"
                @click="openPackPicker"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
                </svg>
                <span class="prompt-plus__title">{{ attachedPack.title }}</span>
                <span class="prompt-plus__caret" aria-hidden="true">▾</span>
              </button>
              <button
                v-else
                type="button"
                class="prompt-plus__add"
                :disabled="sending"
                @click="openPackPicker"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                <span>Add Context Pack</span>
              </button>
              <button
                v-if="attachedPack"
                type="button"
                class="prompt-plus__remove"
                title="Remove Context Pack from this conversation"
                :disabled="detachingPack || sending"
                @click="clearAttachedPack"
              >
                <span v-if="detachingPack" class="spinner" aria-hidden="true" />
                <span v-else aria-hidden="true">×</span>
                <span class="visually-hidden">Remove pack</span>
              </button>
            </div>
            <button
              class="btn btn--ghost btn--sm"
              type="button"
              :disabled="!canSummarize || summarizing || sending"
              :title="
                !canSummarize
                  ? 'Send at least one user/assistant exchange first'
                  : conversation?.summarized_at
                    ? 'Re-summarize this conversation'
                    : 'Summarize this conversation and extract memories'
              "
              @click="handleWrapUp"
            >
              <span v-if="summarizing" class="spinner" aria-hidden="true" />
              <span>
                {{
                  summarizing
                    ? 'Wrapping up…'
                    : conversation?.summarized_at
                      ? 'Re-wrap up'
                      : 'Wrap up'
                }}
              </span>
            </button>
            <button
              class="btn btn--ghost btn--sm"
              type="button"
              :disabled="sending || summarizing || !conversation"
              @click="handleDeleteConversation"
            >
              Delete chat
            </button>
          </div>
        </header>

        <div
          v-if="!hasKeyForSelectedProvider"
          class="banner banner--warning"
          role="alert"
        >
          <strong>{{ providerLabel(selectedProvider) }} key needed.</strong>
          <span>
            <template v-if="!hasAnyProviderKey">
              Save at least one provider key in
            </template>
            <template v-else>
              The model you picked uses {{ providerLabel(selectedProvider) }}.
              Save that key in
            </template>
            <RouterLink to="/settings">Settings</RouterLink>
            <span v-if="hasAnyProviderKey">
              — or pick a model from a provider you've already configured.
            </span>
          </span>
        </div>

        <div v-if="sendError" class="banner banner--error" role="alert">
          <strong>Send failed.</strong>
          <span>{{ sendError }}</span>
        </div>

        <div v-if="summarizeError" class="banner banner--error" role="alert">
          <strong>Wrap-up failed.</strong>
          <span>{{ summarizeError }}</span>
        </div>

        <div v-if="summarizeBanner" class="banner banner--success" role="status">
          <span>{{ summarizeBanner }}</span>
        </div>

        <section
          v-if="conversation?.summary || memoriesList.length"
          class="summary-panel"
        >
          <header class="summary-panel__header">
            <div class="summary-panel__heading">
              <span class="summary-panel__chip">Summary</span>
              <span
                v-if="conversation?.summarized_at"
                class="summary-panel__time"
              >
                · {{ relativeTime(conversation.summarized_at) }}
              </span>
            </div>
            <button
              v-if="memoriesList.length"
              type="button"
              class="btn btn--ghost btn--sm"
              @click="memoriesOpen = !memoriesOpen"
            >
              {{ memoriesOpen ? 'Hide' : 'Show' }}
              {{ memoriesList.length }}
              {{ memoriesList.length === 1 ? 'memory' : 'memories' }}
            </button>
          </header>

          <p v-if="conversation?.summary" class="summary-panel__text">
            {{ conversation.summary }}
          </p>
          <p v-else class="summary-panel__text text-secondary">
            No summary text — see extracted memories below.
          </p>

          <div
            v-if="memoriesOpen && groupedMemories.length"
            class="summary-panel__groups"
          >
            <div
              v-for="group in groupedMemories"
              :key="group.kind"
              class="summary-panel__group"
            >
              <h3 class="summary-panel__group-title">
                {{ group.label }}
                <span class="summary-panel__group-count">
                  {{ group.items.length }}
                </span>
              </h3>
              <ul class="summary-panel__list">
                <li
                  v-for="item in group.items"
                  :key="item.id"
                  class="summary-panel__item"
                >
                  <p class="summary-panel__item-content">{{ item.content }}</p>
                  <p
                    v-if="item.source_excerpt"
                    class="summary-panel__item-excerpt"
                  >
                    “{{ item.source_excerpt }}”
                  </p>
                </li>
              </ul>
            </div>
          </div>
        </section>

        <MessageList
          :messages="messages"
          :pending="sending"
          :highlight-id="highlightId"
        />

        <ChatComposer
          ref="composer"
          :pending="sending"
          :disabled="composerDisabled"
          :placeholder="composerPlaceholder"
          @submit="handleSubmit"
        >
          <template #leading>
            <ModelPicker
              :models="userModels"
              :current-model="selectedModel"
              :current-provider="selectedProvider"
              :disabled="sending"
              @select="onModelPicked"
            />
          </template>
        </ChatComposer>
      </section>
    </div>

    <!-- R13: Context Pack picker modal -->
    <div
      v-if="packPickerOpen"
      class="pack-picker-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pack-picker-title"
      @click.self="closePackPicker"
    >
      <div class="pack-picker">
        <header class="pack-picker__header">
          <div>
            <h2 id="pack-picker-title" class="pack-picker__title">
              Attach a Context Pack
            </h2>
            <p class="pack-picker__hint text-secondary">
              The pack body becomes a leading system message for every reply
              in this conversation. You can swap or remove it any time.
            </p>
          </div>
          <button
            type="button"
            class="pack-picker__close"
            aria-label="Close"
            @click="closePackPicker"
          >
            ×
          </button>
        </header>

        <div class="pack-picker__filters">
          <div class="pack-picker__tabs" role="tablist">
            <button
              type="button"
              role="tab"
              class="pack-picker__tab"
              :class="{ 'pack-picker__tab--active': packPickerScope === 'project' }"
              :aria-selected="packPickerScope === 'project'"
              @click="packPickerScope = 'project'"
            >
              This project
            </button>
            <button
              type="button"
              role="tab"
              class="pack-picker__tab"
              :class="{ 'pack-picker__tab--active': packPickerScope === 'all' }"
              :aria-selected="packPickerScope === 'all'"
              @click="packPickerScope = 'all'"
            >
              All your packs
            </button>
          </div>
          <input
            v-model="packPickerQuery"
            type="search"
            class="pack-picker__search"
            placeholder="Search packs by title or preview…"
            aria-label="Search packs"
          />
        </div>

        <div v-if="packPickerError" class="banner banner--error" role="alert">
          <span>{{ packPickerError }}</span>
          <button type="button" class="btn btn--ghost btn--sm" @click="loadAvailablePacks">
            Try again
          </button>
        </div>

        <div v-if="packsLoading" class="pack-picker__state">
          <span class="spinner" aria-hidden="true" />
          <span class="text-secondary">Loading packs…</span>
        </div>
        <div v-else-if="!filteredPacks.length" class="pack-picker__state">
          <p class="text-secondary">
            <template v-if="!availablePacks.length">
              No Context Packs yet. Create one from a project's detail page.
            </template>
            <template v-else-if="packPickerQuery">
              No packs match “{{ packPickerQuery }}”.
            </template>
            <template v-else-if="packPickerScope === 'project'">
              No packs for this project yet.
              <button
                type="button"
                class="link-btn"
                @click="packPickerScope = 'all'"
              >
                Show packs from other projects
              </button>
            </template>
            <template v-else>No packs match that filter.</template>
          </p>
        </div>
        <ul v-else class="pack-picker__list">
          <li
            v-for="p in filteredPacks"
            :key="p.id"
            class="pack-picker__item"
            :class="{
              'pack-picker__item--active': attachedPack && attachedPack.id === p.id
            }"
          >
            <div class="pack-picker__item-main">
              <div class="pack-picker__item-head">
                <h3 class="pack-picker__item-title">{{ p.title }}</h3>
                <span
                  v-if="p.project_id !== projectIdNum && p.project?.name"
                  class="pack-picker__cross-chip"
                  :title="`From ${p.project.name}`"
                >
                  {{ p.project.name }}
                </span>
              </div>
              <p
                v-if="p.body_preview"
                class="pack-picker__item-preview"
              >
                {{ p.body_preview }}
              </p>
              <p class="pack-picker__item-meta text-secondary">
                <span v-if="p.memory_count != null">
                  {{ p.memory_count }} {{ p.memory_count === 1 ? 'memory' : 'memories' }}
                </span>
                <span v-if="p.created_at">
                  · {{ relativeTime(p.created_at) }}
                </span>
              </p>
            </div>
            <button
              type="button"
              class="btn btn--primary btn--sm"
              :disabled="bindingPackId !== null || (attachedPack && attachedPack.id === p.id)"
              @click="selectPack(p.id)"
            >
              <span v-if="bindingPackId === p.id" class="spinner" aria-hidden="true" />
              <template v-if="attachedPack && attachedPack.id === p.id">
                Attached
              </template>
              <template v-else>Use this</template>
            </button>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-height: calc(100vh - var(--layout-header-h) - var(--space-7));
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
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
}

.banner strong {
  font-weight: 600;
}

.banner--error {
  background: var(--color-error-soft);
  border-color: rgba(217, 48, 37, 0.4);
  color: var(--color-error);
}

.banner--warning {
  background: var(--color-warning-soft);
  border-color: rgba(176, 96, 0, 0.4);
  color: var(--color-warning);
}

.banner--success {
  background: var(--color-primary-soft);
  border-color: rgba(26, 115, 232, 0.35);
  color: var(--color-primary);
}

.banner a {
  color: inherit;
  font-weight: 600;
  text-decoration: underline;
}

.summary-panel {
  margin: 0 var(--space-5);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-alt, var(--color-surface));
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.summary-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.summary-panel__heading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
}

.summary-panel__chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.summary-panel__time {
  color: var(--color-text-muted);
}

.summary-panel__text {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.55;
  color: var(--color-text-primary);
  white-space: pre-wrap;
}

.summary-panel__groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--color-border);
}

.summary-panel__group-title {
  margin: 0 0 6px;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.summary-panel__group-count {
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

.summary-panel__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.summary-panel__item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}

.summary-panel__item-content {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  line-height: 1.45;
}

.summary-panel__item-excerpt {
  margin: 4px 0 0;
  font-size: var(--text-xs);
  font-style: italic;
  color: var(--color-text-muted);
  line-height: 1.45;
  white-space: pre-wrap;
}

.chat-sidebar__badge {
  display: inline-flex;
  align-items: center;
  margin-left: auto;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.chat-layout {
  flex: 1;
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: var(--space-4);
  min-height: 480px;
  align-items: stretch;
}

.chat-sidebar {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  min-height: 0;
}

.chat-sidebar__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.chat-sidebar__breadcrumb {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
}

.chat-sidebar__title {
  margin: 2px 0 0;
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--color-text-primary);
}

.chat-sidebar__loading {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-3) var(--space-4);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.chat-sidebar__list {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chat-sidebar__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  text-decoration: none;
  color: inherit;
  border: 1px solid transparent;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.chat-sidebar__item:hover {
  background: var(--color-surface-hover);
}

.chat-sidebar__item--active {
  background: var(--color-primary-soft);
  border-color: rgba(26, 115, 232, 0.25);
}

.chat-sidebar__item--active .chat-sidebar__item-title {
  color: var(--color-primary);
}

.chat-sidebar__item-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-sidebar__item-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chat-sidebar__empty {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.chat-shell {
  display: flex;
  flex-direction: column;
  min-height: 480px;
  padding: 0;
  overflow: hidden;
}

.chat-header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: flex-end;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.chat-header__breadcrumb {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
}

.chat-header__title {
  margin: 4px 0 0;
  font-size: var(--text-lg);
  font-weight: 500;
  color: var(--color-text-primary);
  word-break: break-word;
}

.chat-header__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

@media (max-width: 960px) {
  .chat-layout {
    grid-template-columns: 1fr;
  }
  .chat-sidebar {
    min-height: auto;
    max-height: 280px;
  }
}

@media (max-width: 720px) {
  .chat-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .chat-header__controls {
    width: 100%;
  }
}

/* ---- R13: Prompt+ pill ---- */
.prompt-plus {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px 2px 8px;
  border-radius: 999px;
  background: var(--color-surface-hover);
  border: 1px dashed var(--color-border);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  max-width: 320px;
}

.prompt-plus--active {
  background: var(--color-primary-soft);
  border-style: solid;
  border-color: rgba(26, 115, 232, 0.4);
  color: var(--color-primary);
}

.prompt-plus__label {
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 10px;
  padding-right: 2px;
  white-space: nowrap;
}

.prompt-plus__add,
.prompt-plus__chip,
.prompt-plus__remove {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: none;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: var(--text-xs);
  color: inherit;
  cursor: pointer;
  font: inherit;
  line-height: 1;
}

.prompt-plus__add:hover:not(:disabled),
.prompt-plus__chip:hover:not(:disabled) {
  background: var(--color-surface);
  color: var(--color-text-primary);
}

.prompt-plus--active .prompt-plus__chip {
  background: var(--color-surface);
  color: var(--color-primary);
  font-weight: 600;
  max-width: 220px;
}

.prompt-plus__title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 160px;
}

.prompt-plus__caret {
  font-size: 10px;
  color: var(--color-text-muted);
}

.prompt-plus__remove {
  width: 22px;
  height: 22px;
  padding: 0;
  justify-content: center;
  font-size: 16px;
  color: var(--color-text-muted);
}

.prompt-plus__remove:hover:not(:disabled) {
  background: rgba(198, 40, 40, 0.1);
  color: #b71c1c;
}

.prompt-plus__add:disabled,
.prompt-plus__chip:disabled,
.prompt-plus__remove:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* ---- R13: Pack picker modal ---- */
.pack-picker-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  z-index: 1000;
}

.pack-picker {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
  width: 100%;
  max-width: 640px;
  max-height: min(80vh, 720px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pack-picker__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.pack-picker__title {
  margin: 0 0 4px;
  font-size: var(--text-lg, 18px);
  font-weight: 600;
}

.pack-picker__hint {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.5;
}

.pack-picker__close {
  background: none;
  border: none;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  color: var(--color-text-muted);
  padding: 4px 8px;
  border-radius: var(--radius-sm);
}

.pack-picker__close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.pack-picker__filters {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-muted, var(--color-surface));
}

.pack-picker__tabs {
  display: inline-flex;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  padding: 2px;
  width: fit-content;
}

.pack-picker__tab {
  background: transparent;
  border: none;
  padding: 6px 14px;
  font-size: var(--text-xs);
  font-weight: 500;
  border-radius: 999px;
  cursor: pointer;
  color: var(--color-text-secondary);
}

.pack-picker__tab--active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.pack-picker__search {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  font-size: var(--text-sm);
}

.pack-picker__search:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.pack-picker__state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-5);
  text-align: center;
  flex-direction: column;
}

.pack-picker__list {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pack-picker__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}

.pack-picker__item--active {
  border-color: rgba(26, 115, 232, 0.5);
  background: var(--color-primary-soft);
}

.pack-picker__item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pack-picker__item-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.pack-picker__item-title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
  word-break: break-word;
}

.pack-picker__cross-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.pack-picker__item-preview {
  margin: 4px 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pack-picker__item-meta {
  margin: 4px 0 0;
  font-size: var(--text-xs);
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

@media (max-width: 720px) {
  .prompt-plus {
    max-width: 100%;
  }
  .prompt-plus__title {
    max-width: 120px;
  }
}
</style>
