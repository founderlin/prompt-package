<template>
  <div class="packs-view">
    <PageHeader
      title="Context Packs"
      description="Generate a structured pack from a project's memories and paste it into any new AI session to keep context."
    >
      <template #actions>
        <RouterLink to="/projects" class="btn btn--primary">
          {{ packs.length ? 'Generate from a project' : 'Open a project' }}
        </RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading && !packs.length" class="state-card">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading Context Packs…</span>
    </div>

    <div v-else-if="errorMessage" class="banner banner--error" role="alert">
      <strong>Could not load Context Packs.</strong>
      <span>{{ errorMessage }}</span>
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
              id: String(pack.project_id),
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
          <div class="pack-row__actions">
            <button
              class="pack-row__copy"
              type="button"
              :title="copiedPackId === pack.id ? 'Copied!' : 'Copy pack'"
              @click.prevent.stop="copyPack(pack)"
            >
              {{ copiedPackId === pack.id ? 'Copied' : 'Copy' }}
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
      title="No Context Packs yet"
      description="Pick a project that has memories, click Generate Context Pack, and we'll turn them into a copy-paste briefing."
    >
      <template #icon>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M12 3 3 7.5v9L12 21l9-4.5v-9L12 3Z" />
          <path d="m3 7.5 9 4.5 9-4.5" />
          <path d="M12 12v9" />
        </svg>
      </template>
    </EmptyState>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import contextPacksApi from '@/api/contextPacks'
import { describeApiError } from '@/utils/errors'
import { relativeTime } from '@/utils/time'
import { modelLabel } from '@/constants/models'

const packs = ref([])
const loading = ref(true)
const errorMessage = ref('')
const copiedPackId = ref(null)
let copyTimer = null

async function loadPacks() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await contextPacksApi.listRecent({ limit: 30 })
    packs.value = Array.isArray(data?.context_packs) ? data.context_packs : []
  } catch (err) {
    packs.value = []
    errorMessage.value = describeApiError(err, 'Could not load Context Packs.')
  } finally {
    loading.value = false
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
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copiedPackId.value = null
    }, 1800)
  } catch (_e) {
    window.alert('Could not copy to clipboard.')
  }
}

onMounted(loadPacks)

onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<style scoped>
.packs-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
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
  padding: var(--space-4);
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
  align-items: center;
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
</style>
