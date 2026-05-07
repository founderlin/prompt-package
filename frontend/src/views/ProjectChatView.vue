<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import MessageList from '@/components/chat/MessageList.vue'
import ModelPicker from '@/components/chat/ModelPicker.vue'
import WrapUpDialog from '@/components/wrapup/WrapUpDialog.vue'
import ChatContextPicker from '@/components/chat/ChatContextPicker.vue'
import chatApi from '@/api/chat'
import contextPacksApi from '@/api/contextPacks'
import memoriesApi from '@/api/memories'
import modelSelectionsApi from '@/api/modelSelections'
import attachmentsApi from '@/api/attachments'
import projectsApi from '@/api/projects'
import { useAuth } from '@/stores/auth'
import { useToasts } from '@/stores/toasts'
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
const toasts = useToasts()

const state = ref('loading')
const errorMessage = ref('')
const project = ref(null)
const conversation = ref(null)
const messages = ref([])
const sending = ref(false)
const sendError = ref('')
// AbortController for the in-flight chat-completion request. Non-null
// only while a request is pending so the Stop button can call .abort().
const sendAbortController = ref(null)
const composer = ref(null)
// Set to true right before we call router.replace() to attach the newly
// created conversation id to the URL. The route watcher reads & resets this
// so it knows to skip the re-bootstrap that would otherwise race with any
// in-flight send and produce duplicate message bubbles.
const suppressNextRouteBootstrap = ref(false)

const conversations = ref([])
const conversationsLoading = ref(false)
const creatingNew = ref(false)
// Tracks which sidebar conversation row is mid-deletion so we can show
// a spinner in place of the trash icon without blocking the whole list.
const deletingSidebarId = ref(null)

const summarizing = ref(false)
const summarizeError = ref('')
const summarizeBanner = ref('')
const memoriesList = ref([])
const memoriesOpen = ref(false)

// R-WRAPUP: Conversation-level Context Pack generation. This is separate
// from ``summarizing`` (the legacy memory-extraction flow driven by
// handleWrapUp) — Wrap Up creates a full Context Pack row via the new
// /api/conversations/:id/wrap-up endpoint.
const wrapUpOpen = ref(false)

// R-BLA-NOTE-CHAT: per-message context items chosen via ChatContextPicker.
// Each item is { type: 'bla_note', id: <int>, title: <string> }.
// Cleared automatically after a successful send.
const contextPickerOpen = ref(false)
const selectedContextItems = ref([])
// Composer draft is usually managed inside ChatComposer (which has an
// internal ref initialized from :model-value). We bind v-model so
// "Insert to input" from the context picker can append text to it.
const composerDraft = ref('')

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

// Pending attachments for the *next* user message. Each entry is either:
//   { clientId, file, status: 'uploading' | 'done' | 'error',
//     filename, size_bytes, kind, progress, previewUrl, id?, error? }
// `id` is populated once the server accepts the upload.
const pendingAttachments = ref([])
const MAX_ATTACH = 8
const ALLOWED_MIME = new Set([
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
const ALLOWED_EXT = /\.(png|jpe?g|webp|gif|pdf|md|markdown|txt)$/i

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
  return 'New blabla'
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
      // We just created a fresh conversation. Push its id into the URL, but
      // flag the watcher so it doesn't re-run bootstrap() in response to the
      // route change we are about to trigger ourselves — doing so would race
      // with any in-flight send and cause duplicate message bubbles.
      suppressNextRouteBootstrap.value = true
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
      errorMessage.value = describeApiError(err, 'Could not load this blabla.')
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

// ---- Attachments ----------------------------------------------------------

function _isAllowedFile(file) {
  if (!file) return false
  if (ALLOWED_MIME.has(file.type)) return true
  return ALLOWED_EXT.test(file.name || '')
}

function _kindForFile(file) {
  if (!file) return 'file'
  const type = file.type || ''
  if (type.startsWith('image/')) return 'image'
  if (type === 'application/pdf' || /\.pdf$/i.test(file.name || '')) return 'pdf'
  return 'text'
}

function _nextClientId() {
  return `att-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

async function handleAddFiles(files) {
  if (!conversation.value) return
  if (!Array.isArray(files) || !files.length) return

  const cid = conversation.value.id
  const accepted = []
  const rejected = []
  for (const f of files) {
    if (pendingAttachments.value.length + accepted.length >= MAX_ATTACH) {
      rejected.push({ file: f, reason: 'limit' })
      continue
    }
    if (!_isAllowedFile(f)) {
      rejected.push({ file: f, reason: 'type' })
      continue
    }
    if (f.size > 10 * 1024 * 1024) {
      rejected.push({ file: f, reason: 'size' })
      continue
    }
    accepted.push(f)
  }

  if (rejected.length) {
    const kinds = new Set(rejected.map((r) => r.reason))
    const parts = []
    if (kinds.has('limit'))
      parts.push(`only ${MAX_ATTACH} attachments per message`)
    if (kinds.has('type'))
      parts.push('only PDF, PNG, JPG, WEBP, GIF, TXT, MD allowed')
    if (kinds.has('size')) parts.push('each file must be under 10 MB')
    sendError.value = `Some files were skipped: ${parts.join('; ')}.`
  }

  // Create local rows immediately so the UI reflects uploading state.
  const entries = accepted.map((f) => ({
    clientId: _nextClientId(),
    file: f,
    status: 'uploading',
    progress: 0,
    filename: f.name,
    size_bytes: f.size,
    kind: _kindForFile(f),
    previewUrl:
      f.type.startsWith('image/') && typeof URL?.createObjectURL === 'function'
        ? URL.createObjectURL(f)
        : null,
    id: null,
    error: null
  }))
  pendingAttachments.value = [...pendingAttachments.value, ...entries]

  for (const entry of entries) {
    try {
      const data = await attachmentsApi.upload(cid, entry.file, {
        onProgress: (frac) => {
          const row = pendingAttachments.value.find(
            (r) => r.clientId === entry.clientId
          )
          if (row) row.progress = frac
        }
      })
      const att = data?.attachment || {}
      const row = pendingAttachments.value.find(
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
      const row = pendingAttachments.value.find(
        (r) => r.clientId === entry.clientId
      )
      if (row) {
        row.status = 'error'
        row.error = describeApiError(err, 'Upload failed')
      }
    }
  }
}

async function handleRemoveAttachment(att) {
  if (!att) return
  // Revoke preview URL to free memory.
  if (att.previewUrl && typeof URL?.revokeObjectURL === 'function') {
    try {
      URL.revokeObjectURL(att.previewUrl)
    } catch (_e) {
      /* ignore */
    }
  }
  // If it's already on the server, delete there too. Ignore errors —
  // the UI removal is what the user asked for.
  if (att.id && conversation.value) {
    try {
      await attachmentsApi.remove(conversation.value.id, att.id)
    } catch (_e) {
      /* best effort */
    }
  }
  pendingAttachments.value = pendingAttachments.value.filter(
    (r) => r.clientId !== att.clientId
  )
}

function clearPendingAttachments() {
  for (const a of pendingAttachments.value) {
    if (a.previewUrl && typeof URL?.revokeObjectURL === 'function') {
      try {
        URL.revokeObjectURL(a.previewUrl)
      } catch (_e) {
        /* ignore */
      }
    }
  }
  pendingAttachments.value = []
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

  // Block send while any attachment is still uploading.
  const stillUploading = pendingAttachments.value.filter(
    (a) => a.status === 'uploading'
  )
  if (stillUploading.length) {
    sendError.value = 'Wait for attachments to finish uploading.'
    return
  }
  // Drop any failed rows before sending — user has already seen the red state.
  pendingAttachments.value = pendingAttachments.value.filter(
    (a) => a.status !== 'error'
  )

  const attachmentIds = pendingAttachments.value
    .filter((a) => a.status === 'done' && a.id != null)
    .map((a) => a.id)

  // Require either non-empty text or at least one attachment.
  if (!content && attachmentIds.length === 0) {
    sendError.value = 'Type a message or attach a file.'
    return
  }

  sendError.value = ''
  sending.value = true

  // Fresh AbortController for this send; handleStop() calls .abort().
  const controller =
    typeof AbortController !== 'undefined' ? new AbortController() : null
  sendAbortController.value = controller

  const tempUserMsg = {
    _tempId: `tmp-user-${Date.now()}`,
    role: 'user',
    content,
    model: modelId,
    provider: providerId,
    created_at: new Date().toISOString(),
    attachments: pendingAttachments.value
      .filter((a) => a.status === 'done')
      .map((a) => ({
        id: a.id,
        filename: a.filename,
        size_bytes: a.size_bytes,
        kind: a.kind,
        previewUrl: a.previewUrl
      }))
  }
  messages.value = [...messages.value, tempUserMsg]
  composer.value?.reset()

  // Snapshot the preview URLs before we clear, so the bubble can keep
  // rendering the optimistic image thumbnail until the server payload
  // lands with an authenticated download URL of its own.
  const inflightAttachments = pendingAttachments.value.slice()
  clearPendingAttachments()

  try {
    // Snapshot context items at send-time so a successful send can
    // clear the selection without racing with a slow network reply.
    const contextItemsToSend = selectedContextItems.value.map((it) => ({
      type: it.type,
      id: it.id
    }))
    const data = await chatApi.sendMessage(conversation.value.id, {
      content: content || '',
      model: modelId,
      provider: providerId,
      attachmentIds,
      contextItems: contextItemsToSend,
      signal: controller?.signal
    })
    // Replace the optimistic temp bubble with the authoritative pair from
    // the server. Rebuild in one pass so that (a) the temp is definitely
    // gone regardless of whether its object identity survived reactivity
    // wrapping, and (b) we dedupe by `id` in case a concurrent refetch
    // (e.g. from a route change) already pushed the same message in.
    const seenIds = new Set()
    const next = []
    for (const m of messages.value) {
      if (m === tempUserMsg) continue
      if (m?._tempId && m._tempId === tempUserMsg._tempId) continue
      if (m?.id != null) {
        if (seenIds.has(m.id)) continue
        seenIds.add(m.id)
      }
      next.push(m)
    }
    if (data?.user_message) {
      const id = data.user_message.id
      if (id == null || !seenIds.has(id)) {
        if (id != null) seenIds.add(id)
        next.push(data.user_message)
      }
    }
    if (data?.assistant_message) {
      const id = data.assistant_message.id
      if (id == null || !seenIds.has(id)) {
        if (id != null) seenIds.add(id)
        next.push(data.assistant_message)
      }
    }
    messages.value = next
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
      applyConversationModel(
        data.conversation.model,
        data.conversation.provider
      )
    }
    // R-BLA-NOTE-CHAT: the context items we just sent are now persisted
    // on data.user_message.context_metadata — safe to clear the draft
    // selection. Future composes start fresh.
    selectedContextItems.value = []
    // Revoke optimistic preview URLs now that the server has the canonical copy.
    for (const a of inflightAttachments) {
      if (a.previewUrl && typeof URL?.revokeObjectURL === 'function') {
        try {
          URL.revokeObjectURL(a.previewUrl)
        } catch (_e) {
          /* ignore */
        }
      }
    }
    loadConversations()
  } catch (err) {
    const wasAborted =
      err?.name === 'CanceledError' ||
      err?.name === 'AbortError' ||
      err?.code === 'ERR_CANCELED' ||
      (controller && controller.signal.aborted)
    if (wasAborted) {
      // The user hit Stop. Keep whatever's on screen; make sure the
      // optimistic bubble is removed and we re-sync from the server so
      // the user message that was already committed (backend commits
      // user msg before the LLM call) is reflected correctly.
      messages.value = messages.value.filter((m) => m !== tempUserMsg)
      sendError.value = ''
      try {
        const refreshed = await chatApi.listMessages(conversation.value.id)
        if (Array.isArray(refreshed?.messages)) {
          messages.value = refreshed.messages
        }
      } catch (_e) {
        /* ignore — optimistic removal was enough */
      }
    } else {
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
    }
    loadConversations()
  } finally {
    sending.value = false
    sendAbortController.value = null
    nextTick(() => composer.value?.focus())
  }
}

function handleStop() {
  const c = sendAbortController.value
  if (c) {
    try {
      c.abort()
    } catch (_e) {
      /* ignore */
    }
  }
}

async function handleCopyMessage(msg) {
  const text = msg?.content || ''
  if (!text) return
  try {
    await navigator.clipboard?.writeText(text)
  } catch (_err) {
    // Fallback for older browsers / insecure contexts.
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
      /* give up silently — clipboard is best-effort */
    }
  }
}

async function handleDeleteMessage(msg) {
  if (!conversation.value || !msg?.id) return
  const oldId = msg.id
  try {
    await chatApi.deleteMessage(conversation.value.id, oldId)
  } catch (err) {
    sendError.value = describeApiError(err, 'Could not delete the message.')
    return
  }
  // Backend cascades: drop this message + every message with a larger id.
  messages.value = messages.value.filter(
    (m) => m.id == null || Number(m.id) < Number(oldId)
  )
  loadConversations()
}

async function handleRetryMessage(msg) {
  // Fired from any assistant *or* user bubble. We pass the clicked
  // message's id to the backend's /regenerate so it knows exactly
  // which pivot point to rebuild from (rather than always targeting
  // "the latest assistant").
  if (!conversation.value || sending.value) return
  if (!msg) return

  const modelId = (selectedModel.value || DEFAULT_MODEL_ID).trim()
  const providerId = selectedProvider.value || DEFAULT_PROVIDER

  // Optimistically trim everything at/after the pivot so the "thinking…"
  // placeholder lands in the right spot. For assistant pivots that's
  // `id >= pivotId`; for user pivots we only drop strictly greater
  // (the user turn itself stays).
  const pivotId = msg?.id
  if (pivotId != null) {
    if (msg.role === 'assistant') {
      messages.value = messages.value.filter(
        (m) => m.id == null || Number(m.id) < Number(pivotId)
      )
    } else if (msg.role === 'user') {
      messages.value = messages.value.filter(
        (m) => m.id == null || Number(m.id) <= Number(pivotId)
      )
    }
  }

  const controller =
    typeof AbortController !== 'undefined' ? new AbortController() : null
  sendAbortController.value = controller
  sendError.value = ''
  sending.value = true

  try {
    const data = await chatApi.retryAssistant(conversation.value.id, {
      model: modelId,
      provider: providerId,
      messageId: pivotId,
      signal: controller?.signal
    })
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
    const wasAborted =
      err?.name === 'CanceledError' ||
      err?.name === 'AbortError' ||
      err?.code === 'ERR_CANCELED' ||
      (controller && controller.signal.aborted)
    if (!wasAborted) {
      sendError.value = describeApiError(
        err,
        'Could not regenerate the reply.'
      )
    }
    // Always re-sync from the server so the old assistant comes back
    // if the retry failed.
    try {
      const refreshed = await chatApi.listMessages(conversation.value.id)
      if (Array.isArray(refreshed?.messages)) {
        messages.value = refreshed.messages
      }
    } catch (_e) {
      /* ignore */
    }
  } finally {
    sending.value = false
    sendAbortController.value = null
  }
}

async function handleEditMessage(payload) {
  // Payload shape:
  //   { message, content, attachmentIds, resolve, reject }
  // The bubble hands us a promise pair so it can close the editor only
  // after the server accepts the reroll. `attachmentIds` is the final
  // set the user wants (mixing existing + freshly-uploaded ids).
  const {
    message: msg,
    content,
    attachmentIds,
    resolve,
    reject
  } = payload || {}
  if (!conversation.value || !msg?.id || !content) {
    reject && reject(new Error('Missing message or content.'))
    return
  }
  if (sending.value) {
    reject &&
      reject(new Error('A request is already in flight.'))
    return
  }

  const modelId = (selectedModel.value || DEFAULT_MODEL_ID).trim()
  const providerId = selectedProvider.value || DEFAULT_PROVIDER

  // Optimistic trim: drop everything strictly after the pivot user
  // message, and patch its content in place so the UI reflects the
  // new text immediately.
  const pivotId = msg.id
  messages.value = messages.value
    .filter((m) => m.id == null || Number(m.id) <= Number(pivotId))
    .map((m) =>
      m.id != null && Number(m.id) === Number(pivotId)
        ? { ...m, content }
        : m
    )

  const controller =
    typeof AbortController !== 'undefined' ? new AbortController() : null
  sendAbortController.value = controller
  sendError.value = ''
  sending.value = true

  try {
    const data = await chatApi.retryAssistant(conversation.value.id, {
      model: modelId,
      provider: providerId,
      messageId: pivotId,
      content,
      // Only forward attachmentIds when the caller explicitly supplied
      // a list — undefined means "leave the server-side set alone".
      ...(Array.isArray(attachmentIds) ? { attachmentIds } : {}),
      signal: controller?.signal
    })
    if (data?.assistant_message) messages.value.push(data.assistant_message)
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
      applyConversationModel(
        data.conversation.model,
        data.conversation.provider
      )
    }
    // Refresh the messages list from the server so the edited user
    // message gets its new attachments list reflected on the bubble.
    try {
      const refreshed = await chatApi.listMessages(conversation.value.id)
      if (Array.isArray(refreshed?.messages)) {
        messages.value = refreshed.messages
      }
    } catch (_e) {
      /* ignore */
    }
    loadConversations()
    resolve && resolve()
  } catch (err) {
    const wasAborted =
      err?.name === 'CanceledError' ||
      err?.name === 'AbortError' ||
      err?.code === 'ERR_CANCELED' ||
      (controller && controller.signal.aborted)
    if (!wasAborted) {
      sendError.value = describeApiError(
        err,
        'Could not save this edit.'
      )
    }
    // Resync so the old state comes back if the reroll failed.
    try {
      const refreshed = await chatApi.listMessages(conversation.value.id)
      if (Array.isArray(refreshed?.messages)) {
        messages.value = refreshed.messages
      }
    } catch (_e) {
      /* ignore */
    }
    reject &&
      reject(
        err instanceof Error
          ? err
          : new Error(describeApiError(err, 'Could not save this edit.'))
      )
  } finally {
    sending.value = false
    sendAbortController.value = null
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
      'Could not create a new blabla.'
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
  try {
    const data = await chatApi.summarizeConversation(conversation.value.id, {
      model: selectedModel.value || DEFAULT_MODEL_ID
    })
    if (data?.conversation) {
      conversation.value = { ...conversation.value, ...data.conversation }
    }
    const items = Array.isArray(data?.memories) ? data.memories : []
    memoriesList.value = items
    // The old inline summary-panel was removed — feedback is now delivered
    // via a top-center toast. The toast carries a link that jumps the user
    // to the project page's memories section (anchor: #project-memories),
    // which is the single source of truth for extracted memories.
    const count = items.length
    const message = count
      ? `Wrap-up complete · ${count} ${count === 1 ? 'memory' : 'memories'} saved.`
      : 'Wrap-up complete, but the model did not extract any memories.'
    toasts.push({
      kind: 'success',
      message,
      link:
        count && project.value
          ? {
              name: 'project-detail',
              params: { id: String(project.value.id) },
              hash: '#project-memories'
            }
          : null,
      linkText: count ? 'View memories' : ''
    })
    loadConversations()
  } catch (err) {
    summarizeError.value = describeApiError(
      err,
      'Could not summarize this blabla.'
    )
  } finally {
    summarizing.value = false
  }
}

// ---- R-WRAPUP: Conversation-level Context Pack flow ----
function openConversationWrapUp() {
  if (!conversation.value) return
  if (realMessageCount.value < 1) return
  wrapUpOpen.value = true
}

function closeConversationWrapUp() {
  wrapUpOpen.value = false
}

function onConversationWrapUpSuccess(pack /*, job */) {
  toasts.push({
    kind: 'success',
    message: `Wrap Up complete · "${pack?.title || 'Context Pack'}" saved.`,
    link:
      pack && project.value
        ? {
            name: 'project-context-pack',
            params: {
              id: String(project.value.id),
              packId: String(pack.id)
            }
          }
        : null,
    linkText: pack ? 'View Context Pack' : ''
  })
  // Refresh the pack picker list so the freshly-made pack is available
  // for immediate attachment in the Prompt+ flow.
  loadAvailablePacks()
}

function onViewConversationWrapUpPack(pack) {
  wrapUpOpen.value = false
  if (!pack || !project.value) return
  router.push({
    name: 'project-context-pack',
    params: {
      id: String(project.value.id),
      packId: String(pack.id)
    }
  })
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

// ---- R-BLA-NOTE-CHAT: Context picker handlers ------------------------
function openContextPicker() {
  if (!conversation.value) return
  contextPickerOpen.value = true
}

function closeContextPicker() {
  contextPickerOpen.value = false
}

function onContextAttach(items) {
  // Replace the current draft selection wholesale — the picker round-
  // trips the user's full intent each time it's opened, so the
  // returned list is authoritative.
  selectedContextItems.value = Array.isArray(items) ? items.slice() : []
}

function onContextInsert(markdownBlock) {
  if (!markdownBlock) return
  // Append to the composer draft. The composer uses v-model internally
  // on its own `internal` ref; we push through the ref forwarded by
  // `composer.value` when possible, else via a controlled prop. Here
  // the simplest path is a small helper on the composer ref — but the
  // ChatComposer currently exposes only `focus` + `reset`. To avoid
  // breaking its API, we stage the text into a local prop and let the
  // composer sync via watch. For MVP, we set a draft override that
  // the template binds to the composer's :model-value.
  composerDraft.value =
    composerDraft.value && composerDraft.value.trim()
      ? `${composerDraft.value.trimEnd()}\n\n${markdownBlock}`
      : markdownBlock
  nextTick(() => composer.value?.focus())
}

function removeContextItem(itemId) {
  selectedContextItems.value = selectedContextItems.value.filter(
    (it) => it.id !== itemId
  )
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
    'Delete this blabla? This cannot be undone.'
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
    sendError.value = describeApiError(err, 'Could not delete the blabla.')
  }
}

async function handleSidebarDelete(convo) {
  if (!convo || deletingSidebarId.value === convo.id) return
  const ok = window.confirm(
    `Delete "${convo.title || 'New blabla'}"? This cannot be undone.`
  )
  if (!ok) return
  deletingSidebarId.value = convo.id
  const isCurrent =
    conversation.value && conversation.value.id === convo.id
  try {
    await chatApi.deleteConversation(convo.id)
    const remaining = conversations.value.filter((c) => c.id !== convo.id)
    conversations.value = remaining

    if (isCurrent) {
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
    }
  } catch (err) {
    sendError.value = describeApiError(err, 'Could not delete the blabla.')
  } finally {
    deletingSidebarId.value = null
  }
}

onMounted(bootstrap)

watch(
  () => [route.params.id, route.params.cid],
  ([nextId, nextCid], [prevId, prevCid]) => {
    if (nextId !== prevId || nextCid !== prevCid) {
      // When we ourselves called router.replace() to attach the freshly
      // created conversation id to the URL, skip the re-bootstrap. Running
      // bootstrap() again here would refetch messages mid-send and produce
      // duplicated user/assistant bubbles.
      if (suppressNextRouteBootstrap.value) {
        suppressNextRouteBootstrap.value = false
        return
      }
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
  clearPendingAttachments()
})
</script>

<template>
  <div class="chat-view">
    <!-- The old "< Back to {project}" link used to live here. It was
         removed — users now navigate back by clicking the project name
         at the top of the chat-sidebar ("MY CONTEXT / {project name}"). -->

    <div v-if="state === 'loading'" class="state-card">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading blabla…</span>
    </div>

    <div v-else-if="state === 'not-found'" class="state-card state-card--empty">
      <h2 class="state-card__title">Blabla not found</h2>
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
      <strong>Could not load this blabla.</strong>
      <span>{{ errorMessage }}</span>
      <button class="btn btn--ghost btn--sm" type="button" @click="bootstrap">
        Try again
      </button>
    </div>

    <div v-else class="chat-layout">
      <aside class="chat-sidebar card">
        <!-- Sidebar header matches the "MY CONTEXT / Blablas / New"
             design: a small uppercase breadcrumb on top that doubles as
             the back-link to the project page (replaces the removed
             "< Back to project" button), the "Blablas" title, and the
             action buttons on the right. -->
        <header class="chat-sidebar__header">
          <div class="chat-sidebar__titles">
            <RouterLink
              :to="{ name: 'project-detail', params: { id: String(projectIdNum) } }"
              class="chat-sidebar__breadcrumb"
              :title="project?.name ? `Back to ${project.name}` : 'Back to project'"
            >
              MY CONTEXT
            </RouterLink>
            <h2 class="chat-sidebar__title">Blablas</h2>
          </div>
          <div class="chat-sidebar__actions">
            <button
              class="btn btn--primary btn--sm"
              type="button"
              :disabled="creatingNew"
              @click="startNewConversation"
            >
              <span v-if="creatingNew" class="spinner" aria-hidden="true" />
              <span>New</span>
            </button>
            <button
              class="btn btn--ghost btn--sm"
              type="button"
              :disabled="!canSummarize || sending"
              :title="
                !canSummarize
                  ? 'Send at least one user/assistant exchange first'
                  : 'Wrap this blabla into a reusable Context Pack'
              "
              @click="openConversationWrapUp"
            >
              <span>Wrap Up</span>
            </button>
          </div>
        </header>

        <div v-if="conversationsLoading && !conversations.length" class="chat-sidebar__loading">
          <span class="spinner" aria-hidden="true" />
          <span>Loading…</span>
        </div>

        <ul v-else-if="conversations.length" class="chat-sidebar__list">
          <li v-for="convo in conversations" :key="convo.id">
            <div
              class="chat-sidebar__row"
              :class="{
                'chat-sidebar__row--active':
                  conversation && conversation.id === convo.id
              }"
            >
              <RouterLink
                :to="{
                  name: 'project-chat',
                  params: { id: String(projectIdNum), cid: String(convo.id) }
                }"
                class="chat-sidebar__item"
              >
                <span class="chat-sidebar__item-title">
                  {{ convo.title || 'New blabla' }}
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
              <button
                type="button"
                class="chat-sidebar__delete"
                :disabled="deletingSidebarId === convo.id"
                :title="`Delete ${convo.title || 'this blabla'}`"
                aria-label="Delete blabla"
                @click.stop.prevent="handleSidebarDelete(convo)"
              >
                <span
                  v-if="deletingSidebarId === convo.id"
                  class="spinner"
                  aria-hidden="true"
                />
                <svg
                  v-else
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
            </div>
          </li>
        </ul>

        <p v-else class="chat-sidebar__empty">No blablas yet.</p>
      </aside>

      <section class="chat-shell card">
        <!-- The old chat-header (project breadcrumb + title + Prompt+ / Wrap up
             / Delete chat controls) was removed to maximize the vertical
             space of the conversation area. Conversation-level actions
             (New, Wrap up, Delete chat) now live in the left sidebar
             header. Project/conversation title is still available via the
             left sidebar list (active row) and the browser tab title. -->

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

        <!-- The old blue "Wrap-up complete" success banner and the inline
             .summary-panel (with SUMMARY chip, memories grouped by kind)
             used to live here. They were removed in favor of a top-center
             toast notification (see handleWrapUp + ToastHost.vue). The
             canonical place to browse extracted memories is now the
             project detail page (#project-memories anchor). -->

        <MessageList
          :messages="messages"
          :pending="sending"
          :highlight-id="highlightId"
          @copy="handleCopyMessage"
          @retry="handleRetryMessage"
          @delete="handleDeleteMessage"
          @edit="handleEditMessage"
        />

        <!-- R-BLA-NOTE-CHAT: selected context items chips. Renders right
             above the composer so the user never loses track of what's
             about to ride along with the next send. -->
        <ul
          v-if="selectedContextItems.length"
          class="chat-context-chips"
          aria-label="Attached context"
        >
          <li
            v-for="item in selectedContextItems"
            :key="item.id"
            class="chat-context-chip"
          >
            <span class="chat-context-chip__kind">
              {{ item.type === 'bla_note' ? 'Note' : item.type }}
            </span>
            <span class="chat-context-chip__title" :title="item.title">
              {{ item.title || `#${item.id}` }}
            </span>
            <button
              type="button"
              class="chat-context-chip__remove"
              :aria-label="`Remove ${item.title || 'context item'}`"
              @click="removeContextItem(item.id)"
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

        <ChatComposer
          ref="composer"
          v-model="composerDraft"
          :pending="sending"
          :disabled="composerDisabled"
          :placeholder="composerPlaceholder"
          :attachments="pendingAttachments"
          :max-attachments="MAX_ATTACH"
          @submit="handleSubmit"
          @stop="handleStop"
          @add-files="handleAddFiles"
          @remove-attachment="handleRemoveAttachment"
        >
          <template #leading>
            <button
              type="button"
              class="btn btn--ghost btn--sm chat-context-add"
              :disabled="sending || !conversation"
              :title="
                selectedContextItems.length
                  ? `Edit context (${selectedContextItems.length} selected)`
                  : 'Add context for this message'
              "
              @click="openContextPicker"
            >
              <span aria-hidden="true">+</span>
              <span>Context</span>
              <span
                v-if="selectedContextItems.length"
                class="chat-context-add__badge"
              >
                {{ selectedContextItems.length }}
              </span>
            </button>
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
              in this blabla. You can swap or remove it any time.
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

    <WrapUpDialog
      :open="wrapUpOpen"
      scope="conversation"
      :conversation-id="conversation ? conversation.id : null"
      :context-label="conversation ? conversation.title || 'Untitled conversation' : ''"
      @close="closeConversationWrapUp"
      @success="onConversationWrapUpSuccess"
      @view-pack="onViewConversationWrapUpPack"
    />

    <ChatContextPicker
      :open="contextPickerOpen"
      :project-id="projectIdNum"
      :initial-selected-ids="selectedContextItems.map((it) => it.id)"
      @cancel="closeContextPicker"
      @attach="onContextAttach"
      @insert="onContextInsert"
    />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  /* Lock the whole chat route to the viewport so the composer stays
     pinned to the bottom and only the message list scrolls.
     AppShell wraps us in .shell__content with `padding: 32px 32px 48px`
     (= --space-6 top, --space-7 bottom). We must subtract those so the
     chat view doesn't overflow past the visible area and push the
     composer below the fold. */
  height: calc(
    100vh
    - var(--layout-header-h)
    - var(--space-6) /* shell__content top padding */
    - var(--space-7) /* shell__content bottom padding */
  );
  min-height: 0;
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
  flex-shrink: 0;
}

/* Banner inside the chat-shell gets sensible horizontal margin so it
   doesn't hug the scrollbar-less edges. The outermost error banner
   (state==='error') lives on .chat-view and inherits the default. */
.chat-shell > .banner {
  margin: var(--space-2) var(--space-5) 0;
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
  flex-shrink: 0;
  max-height: 30vh;
  overflow-y: auto;
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
  /* Conversation list moved to the RIGHT; main chat area takes the
     remaining space on the left/center. DOM order is kept as-is
     (sidebar first, shell second) for accessibility / tab order, and
     we use grid-template-areas + named areas to swap the visual
     positions without re-ordering the markup. */
  grid-template-columns: minmax(0, 1fr) 280px;
  grid-template-areas: 'main side';
  gap: var(--space-4);
  min-height: 0;
  align-items: stretch;
}

.chat-sidebar {
  grid-area: side;
}

.chat-shell {
  grid-area: main;
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

/* Left half of the header: stacked breadcrumb + title. */
.chat-sidebar__titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

/* Two action buttons ("New", "Wrap") stacked on the right side of the
   header. flex-wrap handles very narrow sidebars gracefully. */
.chat-sidebar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* Breadcrumb doubles as the "back to project" link; style it so the
   clickability reads (hover underline + primary color) without making
   it look like a regular body link. */
.chat-sidebar__breadcrumb {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  text-decoration: none;
  cursor: pointer;
  transition: color 0.12s ease;
}

.chat-sidebar__breadcrumb:hover,
.chat-sidebar__breadcrumb:focus-visible {
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
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

/* A sidebar row wraps the RouterLink (main click target) + a hover-
   revealed delete button. The RouterLink keeps its own padding/focus
   ring so keyboard nav still works, while the delete button floats
   absolutely over the right edge and only appears on hover. */
.chat-sidebar__row {
  position: relative;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.chat-sidebar__row:hover {
  background: var(--color-surface-hover);
}

.chat-sidebar__row--active {
  background: var(--color-primary-soft);
  border-color: rgba(26, 115, 232, 0.25);
}

.chat-sidebar__row--active .chat-sidebar__item-title {
  color: var(--color-primary);
}

.chat-sidebar__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  /* Reserve room on the right so the title doesn't get clipped by the
     delete button when it appears on hover. */
  padding: var(--space-2) 36px var(--space-2) var(--space-3);
  text-decoration: none;
  color: inherit;
  border-radius: var(--radius-sm);
}

.chat-sidebar__item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.chat-sidebar__delete {
  position: absolute;
  top: 50%;
  right: 6px;
  transform: translateY(-50%);
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.12s ease, background-color 0.12s ease,
    color 0.12s ease, border-color 0.12s ease;
}

.chat-sidebar__row:hover .chat-sidebar__delete,
.chat-sidebar__row:focus-within .chat-sidebar__delete,
.chat-sidebar__delete:focus-visible {
  opacity: 1;
}

.chat-sidebar__delete:hover:not(:disabled) {
  background: rgba(198, 40, 40, 0.1);
  color: #c62828;
  border-color: rgba(198, 40, 40, 0.35);
}

.chat-sidebar__delete:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (hover: none) {
  /* Touch: always show the delete button so it's reachable. */
  .chat-sidebar__delete {
    opacity: 1;
  }
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
  min-height: 0;
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
  flex-shrink: 0;
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
    /* On narrow screens stack the conversation list above the chat
       shell — tapping a conversation is easier at the top of the
       screen than hidden to the right. */
    grid-template-areas:
      'side'
      'main';
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

/* ---- R-BLA-NOTE-CHAT: context chips + add button -------------------- */

.chat-context-chips {
  list-style: none;
  margin: 0 var(--space-5) 8px;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chat-context-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 4px 3px 10px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border: 1px solid rgba(26, 115, 232, 0.25);
  border-radius: 999px;
  font-size: var(--text-xs);
  max-width: 260px;
  min-width: 0;
}

.chat-context-chip__kind {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
  opacity: 0.75;
  flex-shrink: 0;
}

.chat-context-chip__title {
  font-weight: 500;
  max-width: 180px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.chat-context-chip__remove {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: inherit;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}

.chat-context-chip__remove:hover {
  background: rgba(26, 115, 232, 0.15);
}

.chat-context-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 500;
  height: 30px;
}

.chat-context-add__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  padding: 0 5px;
  height: 18px;
  background: var(--color-primary);
  color: var(--color-text-on-primary);
  border-radius: 999px;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
}
</style>
