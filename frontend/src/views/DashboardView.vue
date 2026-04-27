<template>
  <div class="dashboard">
    <PageHeader
      :title="welcomeTitle"
      description="Capture every AI conversation you have on OpenRouter and turn it into project memory you can reuse later."
    >
      <template #actions>
        <RouterLink to="/projects" class="btn btn--primary">
          {{ projectCount > 0 ? 'View projects' : 'New project' }}
        </RouterLink>
      </template>
    </PageHeader>

    <section class="metrics">
      <article class="metric-card">
        <span class="metric-card__label">Projects</span>
        <span class="metric-card__value">
          <span v-if="projectsLoading" class="spinner" aria-hidden="true" />
          <template v-else>{{ projectCount }}</template>
        </span>
        <span class="metric-card__hint">
          <template v-if="projectsLoading">Loading…</template>
          <template v-else-if="projectCount === 0">Create your first one</template>
          <template v-else>{{ projectCount === 1 ? '1 project' : `${projectCount} projects` }} on file</template>
        </span>
      </article>
      <article class="metric-card">
        <span class="metric-card__label">Conversations</span>
        <span class="metric-card__value">
          <span v-if="conversationsLoading" class="spinner" aria-hidden="true" />
          <template v-else>{{ conversationTotal }}</template>
        </span>
        <span class="metric-card__hint">
          <template v-if="conversationsLoading">Loading…</template>
          <template v-else-if="conversationTotal === 0">Saved automatically when you chat</template>
          <template v-else>{{ conversationTotal === 1 ? '1 conversation' : `${conversationTotal} conversations` }} on file</template>
        </span>
      </article>
      <article class="metric-card">
        <span class="metric-card__label">Context Packs</span>
        <span class="metric-card__value">
          <span v-if="packsLoading" class="spinner" aria-hidden="true" />
          <template v-else>{{ packTotal }}</template>
        </span>
        <span class="metric-card__hint">
          <template v-if="packsLoading">Loading…</template>
          <template v-else-if="packTotal === 0">Generated from project memories</template>
          <template v-else>{{ packTotal === 1 ? '1 pack' : `${packTotal} packs` }} on file</template>
        </span>
      </article>
    </section>

    <div class="dashboard__grid">
      <section class="card">
        <header class="card-header-row">
          <h3 class="card__title card__title--sm">System status</h3>
          <button
            class="btn btn--ghost btn--sm"
            type="button"
            :disabled="state === 'loading'"
            @click="loadHealth"
          >
            <span v-if="state === 'loading'" class="spinner" aria-hidden="true" />
            <span>{{ state === 'loading' ? 'Refreshing' : 'Refresh' }}</span>
          </button>
        </header>

        <div class="status-row">
          <span class="status-row__label">Backend API</span>
          <span v-if="state === 'loading'" class="chip">
            <span class="spinner" aria-hidden="true" />
            Checking…
          </span>
          <span v-else-if="state === 'ok'" class="chip chip--success">
            <span class="dot dot--success" aria-hidden="true" />
            Online
          </span>
          <span v-else class="chip chip--error">
            <span class="dot dot--error" aria-hidden="true" />
            Offline
          </span>
        </div>

        <dl v-if="state === 'ok' && health" class="status-grid">
          <div class="status-grid__cell">
            <dt>Service</dt>
            <dd>{{ health.service }}</dd>
          </div>
          <div class="status-grid__cell">
            <dt>Version</dt>
            <dd>{{ health.version }}</dd>
          </div>
          <div class="status-grid__cell">
            <dt>Server time</dt>
            <dd>{{ formattedTime }}</dd>
          </div>
        </dl>

        <p v-else-if="state === 'error'" class="status-error">
          {{ errorMessage }}
        </p>

        <code class="endpoint">GET {{ apiBaseUrl }}/api/health</code>
      </section>

      <section class="card">
        <h3 class="card__title card__title--sm">Get started</h3>
        <ol class="getting-started">
          <li
            class="getting-started__item"
            :class="{ 'getting-started__item--done': hasApiKey }"
          >
            <span class="getting-started__step">1</span>
            <div>
              <p class="getting-started__title">Add an LLM provider key</p>
              <p class="getting-started__hint">
                <template v-if="hasApiKey">
                  Connected: {{ providersSummary }}. Manage or rotate keys any time in
                  <RouterLink to="/settings">Settings</RouterLink>.
                </template>
                <template v-else>
                  Bring your own key from OpenRouter, DeepSeek, or OpenAI. We store it encrypted, never expose it to the browser.
                  <RouterLink to="/settings">Add a key →</RouterLink>
                </template>
              </p>
            </div>
          </li>
          <li
            class="getting-started__item"
            :class="{ 'getting-started__item--done': projectCount > 0 }"
          >
            <span class="getting-started__step">2</span>
            <div>
              <p class="getting-started__title">Create a project</p>
              <p class="getting-started__hint">
                <template v-if="projectCount > 0">
                  {{ projectCount === 1 ? '1 project' : `${projectCount} projects` }}
                  on file.
                  <RouterLink to="/projects">Open Projects →</RouterLink>
                </template>
                <template v-else>
                  Group related chats under a project so memories stay scoped.
                  <RouterLink to="/projects">New project →</RouterLink>
                </template>
              </p>
            </div>
          </li>
          <li
            class="getting-started__item"
            :class="{ 'getting-started__item--done': conversationTotal > 0 }"
          >
            <span class="getting-started__step">3</span>
            <div>
              <p class="getting-started__title">Start chatting</p>
              <p class="getting-started__hint">
                <template v-if="conversationTotal > 0">
                  {{ conversationTotal === 1 ? '1 conversation' : `${conversationTotal} conversations` }}
                  saved so far.
                </template>
                <template v-else>
                  Pick a model, talk to it, and we'll save every turn for you.
                </template>
              </p>
            </div>
          </li>
          <li
            class="getting-started__item"
            :class="{ 'getting-started__item--done': packTotal > 0 }"
          >
            <span class="getting-started__step">4</span>
            <div>
              <p class="getting-started__title">Wrap up &amp; generate a Context Pack</p>
              <p class="getting-started__hint">
                <template v-if="packTotal > 0">
                  {{ packTotal === 1 ? '1 pack' : `${packTotal} packs` }} ready to paste into the next AI session.
                </template>
                <template v-else>
                  After a chat, hit <strong>Wrap up</strong> to extract memories, then generate a Context Pack to bring it all into a fresh session.
                </template>
              </p>
            </div>
          </li>
        </ol>
      </section>
    </div>

    <section class="card">
      <header class="card-header-row">
        <h3 class="card__title card__title--sm">Recent conversations</h3>
        <RouterLink
          v-if="recentConversations.length"
          to="/projects"
          class="link-btn"
        >
          Browse all projects
        </RouterLink>
      </header>

      <div v-if="conversationsLoading" class="status-row">
        <span class="spinner" aria-hidden="true" />
        <span class="status-row__label">Loading conversations…</span>
      </div>

      <div
        v-else-if="conversationsError"
        class="banner banner--error"
        role="alert"
      >
        <strong>Could not load conversations.</strong>
        <span>{{ conversationsError }}</span>
        <button
          class="btn btn--ghost btn--sm"
          type="button"
          @click="loadRecentConversations"
        >
          Retry
        </button>
      </div>

      <ul
        v-else-if="recentConversations.length"
        class="recent-list"
      >
        <li v-for="convo in recentConversations" :key="convo.id" class="recent-row">
          <RouterLink
            :to="{
              name: 'project-chat',
              params: {
                id: String(convo.project_id),
                cid: String(convo.id)
              }
            }"
            class="recent-row__link"
          >
            <div class="recent-row__main">
              <span class="recent-row__title">
                {{ convo.title || 'Untitled conversation' }}
              </span>
              <span class="recent-row__meta">
                <span v-if="convo.project?.name" class="chip chip--primary">
                  {{ convo.project.name }}
                </span>
                <span v-if="convo.model">{{ modelLabel(convo.model) }}</span>
                <span>{{ convo.message_count || 0 }} {{ (convo.message_count || 0) === 1 ? 'msg' : 'msgs' }}</span>
                <span v-if="convo.last_message_at">
                  · {{ relativeTime(convo.last_message_at) }}
                </span>
                <span v-else-if="convo.created_at">
                  · created {{ relativeTime(convo.created_at) }}
                </span>
              </span>
            </div>
            <svg
              class="recent-row__chevron"
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
        title="No conversations yet"
        description="Open a project and click Start chat to send your first message. It'll show up here automatically."
      >
        <template #icon>
          <svg
            xmlns="http://www.w3.org/2000/svg"
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

    <section class="card">
      <header class="card-header-row">
        <h3 class="card__title card__title--sm">Recent Context Packs</h3>
        <RouterLink to="/context-packs" class="link-btn">
          View all
        </RouterLink>
      </header>

      <div v-if="packsLoading" class="status-row">
        <span class="spinner" aria-hidden="true" />
        <span class="status-row__label">Loading Context Packs…</span>
      </div>

      <div
        v-else-if="packsError"
        class="banner banner--error"
        role="alert"
      >
        <strong>Could not load Context Packs.</strong>
        <span>{{ packsError }}</span>
        <button
          class="btn btn--ghost btn--sm"
          type="button"
          @click="loadRecentPacks"
        >
          Retry
        </button>
      </div>

      <ul v-else-if="recentPacks.length" class="recent-list">
        <li v-for="pack in recentPacks" :key="pack.id" class="recent-row">
          <RouterLink
            :to="{
              name: 'project-context-pack',
              params: {
                id: String(pack.project_id),
                packId: String(pack.id)
              }
            }"
            class="recent-row__link"
          >
            <div class="recent-row__main">
              <span class="recent-row__title">{{ pack.title }}</span>
              <span class="recent-row__meta">
                <span v-if="pack.project?.name" class="chip chip--primary">
                  {{ pack.project.name }}
                </span>
                <span v-if="pack.model">{{ modelLabel(pack.model) }}</span>
                <span>
                  · {{ pack.memory_count || 0 }}
                  {{ (pack.memory_count || 0) === 1 ? 'memory' : 'memories' }}
                </span>
                <span v-if="pack.created_at">
                  · {{ relativeTime(pack.created_at) }}
                </span>
              </span>
            </div>
            <svg
              class="recent-row__chevron"
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
        title="No Context Packs yet"
        description="Open a project with memories and click Generate Context Pack — your packs will appear here."
      >
        <template #icon>
          <svg
            xmlns="http://www.w3.org/2000/svg"
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchHealth } from '@/api/health'
import projectsApi from '@/api/projects'
import chatApi from '@/api/chat'
import contextPacksApi from '@/api/contextPacks'
import { useAuth } from '@/stores/auth'
import { describeApiError } from '@/utils/errors'
import { relativeTime } from '@/utils/time'
import { modelLabel } from '@/constants/models'

const auth = useAuth()

const projectCount = ref(0)
const projectsLoading = ref(true)

const recentConversations = ref([])
const conversationTotal = ref(0)
const conversationsLoading = ref(true)
const conversationsError = ref('')

const recentPacks = ref([])
const packTotal = ref(0)
const packsLoading = ref(true)
const packsError = ref('')

const welcomeTitle = computed(() => {
  const email = auth.user.value?.email
  if (!email) return 'Welcome back'
  const handle = email.split('@')[0]
  return `Welcome back, ${handle}`
})

const providersConfigured = computed(() => {
  const u = auth.user.value
  if (u?.providers && typeof u.providers === 'object') return u.providers
  return {
    openrouter: !!u?.has_openrouter_api_key,
    deepseek: false,
    openai: false
  }
})

const configuredProviders = computed(() =>
  Object.entries(providersConfigured.value)
    .filter(([, on]) => on)
    .map(([id]) => id)
)

const hasApiKey = computed(() => configuredProviders.value.length > 0)

const providersSummary = computed(() => {
  const labels = {
    openrouter: 'OpenRouter',
    deepseek: 'DeepSeek',
    openai: 'OpenAI'
  }
  return configuredProviders.value.map((id) => labels[id] || id).join(', ')
})

const state = ref('loading')
const health = ref(null)
const errorMessage = ref('')

const apiBaseUrl = computed(
  () => import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5001'
)

const formattedTime = computed(() => {
  if (!health.value?.timestamp) return ''
  try {
    return new Date(health.value.timestamp).toLocaleString()
  } catch (_e) {
    return health.value.timestamp
  }
})

async function loadHealth() {
  state.value = 'loading'
  errorMessage.value = ''
  try {
    const data = await fetchHealth()
    health.value = data
    state.value = data?.status === 'ok' ? 'ok' : 'error'
    if (state.value === 'error') {
      errorMessage.value = 'Backend responded but status is not ok.'
    }
  } catch (err) {
    state.value = 'error'
    errorMessage.value = describeError(err)
  }
}

function describeError(err) {
  if (err?.response) {
    return `Backend returned ${err.response.status} ${err.response.statusText || ''}`.trim()
  }
  if (err?.request) {
    return 'Could not reach the backend. Is Flask running on the configured port?'
  }
  return err?.message || 'Unknown error talking to the backend.'
}

async function loadProjectCount() {
  projectsLoading.value = true
  try {
    const data = await projectsApi.list()
    projectCount.value = data?.total ?? data?.projects?.length ?? 0
  } catch (_e) {
    projectCount.value = 0
  } finally {
    projectsLoading.value = false
  }
}

async function loadRecentConversations() {
  conversationsLoading.value = true
  conversationsError.value = ''
  try {
    const data = await chatApi.listAllConversations({ limit: 5 })
    recentConversations.value = Array.isArray(data?.conversations)
      ? data.conversations
      : []
    conversationTotal.value = data?.total ?? recentConversations.value.length
  } catch (err) {
    recentConversations.value = []
    conversationTotal.value = 0
    conversationsError.value = describeApiError(
      err,
      'Could not load conversations.'
    )
  } finally {
    conversationsLoading.value = false
  }
}

async function loadRecentPacks() {
  packsLoading.value = true
  packsError.value = ''
  try {
    const data = await contextPacksApi.listRecent({ limit: 5 })
    recentPacks.value = Array.isArray(data?.context_packs)
      ? data.context_packs
      : []
    packTotal.value = data?.total ?? recentPacks.value.length
  } catch (err) {
    recentPacks.value = []
    packTotal.value = 0
    packsError.value = describeApiError(err, 'Could not load Context Packs.')
  } finally {
    packsLoading.value = false
  }
}

onMounted(() => {
  loadHealth()
  loadProjectCount()
  loadRecentConversations()
  loadRecentPacks()
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-4);
}

.metric-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  box-shadow: var(--shadow-1);
}

.metric-card__label {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  font-weight: 500;
}

.metric-card__value {
  font-size: var(--text-3xl);
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.1;
}

.metric-card__hint {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.dashboard__grid {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: var(--space-4);
}

@media (max-width: 880px) {
  .dashboard__grid {
    grid-template-columns: 1fr;
  }
}

.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.status-row__label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: 500;
}

.status-grid {
  margin: var(--space-4) 0 var(--space-3);
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-3);
}

.status-grid__cell {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
}

.status-grid__cell dt {
  margin: 0 0 var(--space-1);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-text-muted);
}

.status-grid__cell dd {
  margin: 0;
  font-size: var(--text-base);
  word-break: break-all;
}

.status-error {
  margin: var(--space-3) 0;
  font-size: var(--text-sm);
  color: var(--color-error);
}

.endpoint {
  display: inline-block;
  margin-top: var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  padding: 4px 8px;
  border-radius: var(--radius-xs);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.dot--success {
  background: var(--color-success);
}

.dot--error {
  background: var(--color-error);
}

.getting-started {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.getting-started__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
}

.getting-started__step {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-sm);
  font-weight: 500;
}

.getting-started__item--done .getting-started__step {
  background: var(--color-success);
  border-color: var(--color-success);
  color: #fff;
}

.getting-started__title {
  margin: 0 0 2px;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-primary);
}

.getting-started__hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
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

.link-btn {
  font-size: var(--text-sm);
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}

.link-btn:hover {
  text-decoration: underline;
}

.recent-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.recent-row__link {
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

.recent-row__link:hover {
  background: var(--color-surface-hover);
  border-color: var(--color-border);
}

.recent-row__main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
}

.recent-row__title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.recent-row__meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.recent-row__chevron {
  color: var(--color-text-muted);
  flex-shrink: 0;
}
</style>
