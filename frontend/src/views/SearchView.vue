<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import searchApi from '@/api/search'
import { describeApiError } from '@/utils/errors'
import { highlightSegments } from '@/utils/highlight'
import { relativeTime } from '@/utils/time'
import { modelLabel } from '@/constants/models'

const route = useRoute()
const router = useRouter()

const TABS = [
  { id: 'all', label: 'All' },
  { id: 'messages', label: 'Messages' },
  { id: 'memories', label: 'Memories' },
  { id: 'conversations', label: 'Conversations' }
]

const VALID_TABS = new Set(TABS.map((t) => t.id))

const MEMORY_KIND_LABEL = {
  fact: 'Fact',
  decision: 'Decision',
  todo: 'Todo',
  question: 'Question'
}

const ROLE_LABEL = {
  user: 'You',
  assistant: 'Model'
}

const queryInput = ref(typeof route.query.q === 'string' ? route.query.q : '')
const activeTab = ref(
  typeof route.query.type === 'string' && VALID_TABS.has(route.query.type)
    ? route.query.type
    : 'all'
)

const lastQuery = ref('')
const loading = ref(false)
const errorMessage = ref('')
const results = ref({ messages: [], memories: [], conversations: [] })
const totals = ref({ messages: 0, memories: 0, conversations: 0 })

const grandTotal = computed(
  () =>
    (totals.value.messages || 0) +
    (totals.value.memories || 0) +
    (totals.value.conversations || 0)
)

const visibleSections = computed(() => {
  const all = [
    { id: 'messages', label: 'Messages', items: results.value.messages },
    { id: 'memories', label: 'Memories', items: results.value.memories },
    {
      id: 'conversations',
      label: 'Conversations',
      items: results.value.conversations
    }
  ]
  if (activeTab.value === 'all') return all.filter((s) => s.items.length)
  return all.filter((s) => s.id === activeTab.value)
})

const showEmptyResults = computed(
  () =>
    !loading.value &&
    !errorMessage.value &&
    lastQuery.value.length > 0 &&
    grandTotal.value === 0
)

let debounceTimer = null

function scheduleSearch(immediate = false) {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  if (immediate) {
    runSearch()
    return
  }
  debounceTimer = setTimeout(runSearch, 300)
}

async function runSearch() {
  const q = queryInput.value.trim()
  syncRouteQuery(q, activeTab.value)
  if (!q) {
    lastQuery.value = ''
    results.value = { messages: [], memories: [], conversations: [] }
    totals.value = { messages: 0, memories: 0, conversations: 0 }
    errorMessage.value = ''
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await searchApi.search(q)
    lastQuery.value = q
    results.value = data?.results || {
      messages: [],
      memories: [],
      conversations: []
    }
    totals.value = data?.totals || {
      messages: results.value.messages.length,
      memories: results.value.memories.length,
      conversations: results.value.conversations.length
    }
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not run that search.')
    results.value = { messages: [], memories: [], conversations: [] }
    totals.value = { messages: 0, memories: 0, conversations: 0 }
  } finally {
    loading.value = false
  }
}

function syncRouteQuery(q, type) {
  const next = { ...route.query }
  if (q) next.q = q
  else delete next.q
  if (type && type !== 'all') next.type = type
  else delete next.type
  if (
    next.q === route.query.q &&
    next.type === route.query.type &&
    Object.keys(next).length === Object.keys(route.query).length
  ) {
    return
  }
  router.replace({ name: 'search', query: next })
}

function selectTab(tabId) {
  activeTab.value = tabId
  syncRouteQuery(queryInput.value.trim(), tabId)
}

function clearQuery() {
  queryInput.value = ''
  scheduleSearch(true)
}

function tabBadge(tabId) {
  if (tabId === 'all') return grandTotal.value
  return totals.value[tabId] || 0
}

function memoryKindLabel(kind) {
  return MEMORY_KIND_LABEL[kind] || 'Note'
}

function roleLabel(role) {
  return ROLE_LABEL[role] || role
}

function segments(text) {
  return highlightSegments(text, lastQuery.value)
}

function messageRoute(item) {
  return {
    name: 'project-chat',
    params: {
      id: String(item.project.id),
      cid: String(item.conversation.id)
    },
    hash: `#msg-${item.id}`
  }
}

function conversationRoute(item) {
  return {
    name: 'project-chat',
    params: {
      id: String(item.project.id),
      cid: String(item.id)
    }
  }
}

function memoryRoute(item) {
  if (item.conversation && item.conversation.id) {
    return {
      name: 'project-chat',
      params: {
        id: String(item.project.id),
        cid: String(item.conversation.id)
      }
    }
  }
  return {
    name: 'project-detail',
    params: { id: String(item.project.id) }
  }
}

watch(queryInput, () => scheduleSearch(false))

onMounted(() => {
  if (queryInput.value.trim()) {
    runSearch()
  }
})

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<template>
  <div class="search-view">
    <PageHeader
      title="Search"
      description="Search across your messages, memories, and conversation titles. Hits are scoped to your account only."
    />

    <div class="card card--flat search-bar">
      <label class="search-bar__label" for="search-input">Query</label>
      <div class="search-bar__row">
        <div class="search-bar__field">
          <svg
            class="search-bar__icon"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            id="search-input"
            v-model="queryInput"
            class="search-bar__input"
            type="text"
            autocomplete="off"
            placeholder="e.g. pgvector, refactor decision, todo…"
            @keydown.enter.prevent="scheduleSearch(true)"
          />
          <button
            v-if="queryInput"
            class="search-bar__clear"
            type="button"
            aria-label="Clear search"
            @click="clearQuery"
          >
            ×
          </button>
        </div>
      </div>
      <p class="field__hint">
        Searches at most 50 messages, memories, and conversations per type.
      </p>
    </div>

    <nav class="tabs" role="tablist" aria-label="Result types">
      <button
        v-for="tab in TABS"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        class="tab"
        :class="{ 'tab--active': activeTab === tab.id }"
        @click="selectTab(tab.id)"
      >
        <span>{{ tab.label }}</span>
        <span v-if="lastQuery" class="tab__count">{{ tabBadge(tab.id) }}</span>
      </button>
    </nav>

    <div v-if="errorMessage" class="banner banner--error" role="alert">
      <strong>Search failed.</strong>
      <span>{{ errorMessage }}</span>
      <button
        class="btn btn--ghost btn--sm"
        type="button"
        @click="scheduleSearch(true)"
      >
        Retry
      </button>
    </div>

    <div v-if="loading" class="state-row">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Searching…</span>
    </div>

    <template v-else>
      <template v-if="!lastQuery">
        <EmptyState
          title="Type to search"
          description="Search runs as you type. Tip: search the OpenRouter model name (e.g. ‘gpt-4o-mini’) to see every conversation that used it."
        >
          <template #icon>
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
          </template>
        </EmptyState>
      </template>

      <template v-else-if="showEmptyResults">
        <EmptyState
          title="No matches"
          :description="`Nothing found for “${lastQuery}”. Try a different keyword or switch tabs.`"
        >
          <template #icon>
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
              <path d="M8 11h6" />
            </svg>
          </template>
        </EmptyState>
      </template>

      <template v-else>
        <section
          v-for="section in visibleSections"
          :key="section.id"
          class="result-section"
        >
          <header class="result-section__header">
            <h3 class="result-section__title">{{ section.label }}</h3>
            <span class="result-section__count">{{ section.items.length }}</span>
          </header>

          <ul class="result-list">
            <li
              v-for="item in section.items"
              :key="`${section.id}-${item.id}`"
              class="result-card"
            >
              <RouterLink
                v-if="section.id === 'messages'"
                :to="messageRoute(item)"
                class="result-card__link"
              >
                <div class="result-card__head">
                  <span class="chip chip--role">
                    {{ roleLabel(item.role) }}
                  </span>
                  <span class="result-card__breadcrumb">
                    <RouterLink
                      :to="{
                        name: 'project-detail',
                        params: { id: String(item.project.id) }
                      }"
                      class="result-card__crumb-link"
                      @click.stop
                    >
                      {{ item.project.name }}
                    </RouterLink>
                    <span class="result-card__sep">›</span>
                    <span>{{ item.conversation.title || 'Untitled' }}</span>
                  </span>
                </div>
                <p class="result-card__snippet">
                  <template v-for="(seg, i) in segments(item.snippet)" :key="i">
                    <mark v-if="seg.match" class="hl">{{ seg.text }}</mark>
                    <span v-else>{{ seg.text }}</span>
                  </template>
                </p>
                <p class="result-card__meta">
                  <span v-if="item.model">{{ modelLabel(item.model) }}</span>
                  <span v-if="item.created_at">
                    · {{ relativeTime(item.created_at) }}
                  </span>
                </p>
              </RouterLink>

              <RouterLink
                v-else-if="section.id === 'memories'"
                :to="memoryRoute(item)"
                class="result-card__link"
              >
                <div class="result-card__head">
                  <span
                    class="chip"
                    :class="`chip--memory chip--memory-${item.kind}`"
                  >
                    {{ memoryKindLabel(item.kind) }}
                  </span>
                  <span class="result-card__breadcrumb">
                    <RouterLink
                      :to="{
                        name: 'project-detail',
                        params: { id: String(item.project.id) }
                      }"
                      class="result-card__crumb-link"
                      @click.stop
                    >
                      {{ item.project.name }}
                    </RouterLink>
                    <template v-if="item.conversation">
                      <span class="result-card__sep">›</span>
                      <span>{{
                        item.conversation.title || 'Untitled conversation'
                      }}</span>
                    </template>
                  </span>
                </div>
                <p class="result-card__snippet">
                  <template v-for="(seg, i) in segments(item.snippet)" :key="i">
                    <mark v-if="seg.match" class="hl">{{ seg.text }}</mark>
                    <span v-else>{{ seg.text }}</span>
                  </template>
                </p>
                <p
                  v-if="
                    item.match_field === 'source_excerpt' && item.source_excerpt
                  "
                  class="result-card__excerpt"
                >
                  matched in excerpt
                </p>
                <p class="result-card__meta">
                  <span v-if="item.created_at">
                    {{ relativeTime(item.created_at) }}
                  </span>
                </p>
              </RouterLink>

              <RouterLink
                v-else
                :to="conversationRoute(item)"
                class="result-card__link"
              >
                <div class="result-card__head">
                  <span class="chip chip--conversation">Conversation</span>
                  <span class="result-card__breadcrumb">
                    <RouterLink
                      :to="{
                        name: 'project-detail',
                        params: { id: String(item.project.id) }
                      }"
                      class="result-card__crumb-link"
                      @click.stop
                    >
                      {{ item.project.name }}
                    </RouterLink>
                  </span>
                </div>
                <p class="result-card__title">
                  <template v-for="(seg, i) in segments(item.title || 'Untitled conversation')" :key="i">
                    <mark v-if="seg.match" class="hl">{{ seg.text }}</mark>
                    <span v-else>{{ seg.text }}</span>
                  </template>
                </p>
                <p
                  v-if="item.snippet && item.match_field === 'summary'"
                  class="result-card__snippet"
                >
                  <template v-for="(seg, i) in segments(item.snippet)" :key="i">
                    <mark v-if="seg.match" class="hl">{{ seg.text }}</mark>
                    <span v-else>{{ seg.text }}</span>
                  </template>
                </p>
                <p class="result-card__meta">
                  <span v-if="item.model">{{ modelLabel(item.model) }}</span>
                  <span v-if="item.message_count != null">
                    · {{ item.message_count }}
                    {{ item.message_count === 1 ? 'msg' : 'msgs' }}
                  </span>
                  <span v-if="item.summarized_at" class="result-card__badge">
                    Summarized
                  </span>
                  <span v-if="item.last_message_at">
                    · {{ relativeTime(item.last_message_at) }}
                  </span>
                </p>
              </RouterLink>
            </li>
          </ul>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.search-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.search-bar {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.search-bar__label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-secondary);
}

.search-bar__row {
  display: flex;
  gap: var(--space-3);
}

.search-bar__field {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}

.search-bar__icon {
  position: absolute;
  left: 12px;
  color: var(--color-text-muted);
  pointer-events: none;
}

.search-bar__input {
  width: 100%;
  padding: 10px 36px 10px 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  font: inherit;
  color: var(--color-text-primary);
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}

.search-bar__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.search-bar__clear {
  position: absolute;
  right: 8px;
  background: transparent;
  border: none;
  color: var(--color-text-muted);
  font-size: 18px;
  line-height: 1;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  cursor: pointer;
}

.search-bar__clear:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.field__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: var(--space-2);
}

.tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  font: inherit;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease,
    border-color 0.12s ease;
}

.tab:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-primary);
}

.tab--active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-color: rgba(26, 115, 232, 0.25);
  font-weight: 500;
}

.tab__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.tab--active .tab__count {
  background: rgba(26, 115, 232, 0.15);
  color: var(--color-primary);
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

.banner--error {
  background: var(--color-error-soft);
  border-color: rgba(217, 48, 37, 0.4);
  color: var(--color-error);
}

.state-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.result-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.result-section__header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-section__title {
  margin: 0;
  font-size: var(--text-sm);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  font-weight: 600;
}

.result-section__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.result-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.result-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.result-card:hover {
  border-color: rgba(26, 115, 232, 0.25);
  background: var(--color-surface-hover);
}

.result-card__link {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--space-3) var(--space-4);
  text-decoration: none;
  color: inherit;
}

.result-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.result-card__breadcrumb {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  flex-wrap: wrap;
}

.result-card__crumb-link {
  color: var(--color-text-secondary);
  text-decoration: none;
}

.result-card__crumb-link:hover {
  color: var(--color-primary);
  text-decoration: underline;
}

.result-card__sep {
  color: var(--color-text-muted);
}

.result-card__title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.4;
}

.result-card__snippet {
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.5;
  color: var(--color-text-primary);
  white-space: pre-wrap;
}

.result-card__excerpt {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-style: italic;
}

.result-card__meta {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.result-card__badge {
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

.chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.chip--role {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.chip--conversation {
  background: rgba(26, 115, 232, 0.1);
  color: var(--color-primary);
}

.chip--memory {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.chip--memory-decision {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.chip--memory-todo {
  background: rgba(176, 96, 0, 0.12);
  color: var(--color-warning);
}

.chip--memory-fact {
  background: var(--color-surface-hover);
  color: var(--color-text-secondary);
}

.chip--memory-question {
  background: rgba(217, 48, 37, 0.12);
  color: var(--color-error);
}

.hl {
  background: rgba(255, 213, 79, 0.55);
  color: inherit;
  border-radius: 3px;
  padding: 0 1px;
}

@media (max-width: 560px) {
  .search-bar__row {
    flex-direction: column;
  }
}
</style>
