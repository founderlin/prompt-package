<template>
  <div class="projects-view">
    <PageHeader
      title="Projects"
      description="Each project keeps its own blablas, summaries, memories, and Context Packs."
    >
      <template #actions>
        <button
          class="btn btn--primary"
          type="button"
          @click="openCreate"
          :disabled="loading"
        >
          New project
        </button>
      </template>
    </PageHeader>

    <div v-if="loading" class="projects-view__loading">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading your projects…</span>
    </div>

    <div v-else-if="loadError" class="banner banner--error" role="alert">
      <strong>Could not load your projects.</strong>
      <span>{{ loadError }}</span>
      <button class="btn btn--ghost btn--sm" type="button" @click="loadProjects">
        Try again
      </button>
    </div>

    <EmptyState
      v-else-if="projects.length === 0"
      title="No projects yet"
      description="Projects group your blablas, summaries, and Context Packs together. Create your first one to get started."
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
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
      </template>
      <template #actions>
        <button class="btn btn--primary" type="button" @click="openCreate">
          Create your first project
        </button>
      </template>
    </EmptyState>

    <ul v-else class="project-grid">
      <li v-for="project in projects" :key="project.id" class="project-card">
        <header class="project-card__header">
          <RouterLink
            :to="{ name: 'project-detail', params: { id: project.id } }"
            class="project-card__name-link"
          >
            <h3 class="project-card__name">{{ project.name }}</h3>
          </RouterLink>
          <div class="project-card__menu">
            <button
              type="button"
              class="icon-btn"
              :aria-label="`Edit ${project.name}`"
              title="Edit"
              @click="openEdit(project)"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4z" />
              </svg>
            </button>
            <button
              type="button"
              class="icon-btn icon-btn--danger"
              :aria-label="`Delete ${project.name}`"
              title="Delete"
              :disabled="deletingId === project.id"
              @click="onDelete(project)"
            >
              <span v-if="deletingId === project.id" class="spinner" aria-hidden="true" />
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
                <path d="M3 6h18" />
                <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
              </svg>
            </button>
          </div>
        </header>

        <p class="project-card__description">
          {{ project.description || 'No description yet.' }}
        </p>

        <!-- Phase 6: tiny "wrap memory" line — kept to one row so it
             never competes with the description for vertical space. -->
        <div
          class="project-card__memory"
          :class="{ 'project-card__memory--empty': memoryForProject(project.id).wrapCount === 0 }"
          :title="memoryTooltip(project.id)"
        >
          <svg
            class="project-card__memory-icon"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span class="project-card__memory-text">
            <template v-if="statsLoading">
              <span class="spinner spinner--sm" aria-hidden="true" />
              <span>Loading wrap memory…</span>
            </template>
            <template v-else-if="memoryForProject(project.id).wrapCount === 0">
              Wraps: 0 · Memory: 0 B · Last Wrap: Never
            </template>
            <template v-else>
              Wraps: {{ memoryForProject(project.id).wrapCount }} ·
              Memory: {{ formatBytes(memoryForProject(project.id).memorySizeBytes) }} ·
              Last Wrap: {{ formatLastWrapped(memoryForProject(project.id).lastWrappedAt) }}
            </template>
          </span>
        </div>

        <footer class="project-card__footer">
          <span class="project-card__time">
            Updated {{ relativeTime(project.updated_at) || 'just now' }}
          </span>
          <RouterLink
            :to="{ name: 'project-detail', params: { id: project.id } }"
            class="btn btn--ghost btn--sm"
          >
            Open
          </RouterLink>
        </footer>
      </li>
    </ul>

    <ProjectFormDialog
      :open="dialogOpen"
      :project="editingProject"
      @close="closeDialog"
      @created="onCreated"
      @updated="onUpdated"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ProjectFormDialog from '@/components/projects/ProjectFormDialog.vue'
import projectsApi from '@/api/projects'
import wrapsApi from '@/api/wraps'
import { describeApiError } from '@/utils/errors'
import { relativeTime } from '@/utils/time'
import { formatBytes } from '@/utils/bytes'

const projects = ref([])
const loading = ref(true)
const loadError = ref('')
const deletingId = ref(null)

const dialogOpen = ref(false)
const editingProject = ref(null)

// Phase 6: wrap memory stats per project. Keyed by project id so we
// can render each card independently. ``statsLoading`` is true on
// the very first fetch; on subsequent project create/delete we just
// re-request silently in the background.
const memoryByProject = ref({})
const statsLoading = ref(true)

async function loadProjects() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await projectsApi.list()
    projects.value = data?.projects || []
  } catch (err) {
    loadError.value = describeApiError(err, 'Could not load your projects.')
  } finally {
    loading.value = false
  }
}

async function loadMemoryStats() {
  // Fire-and-forget: the cards already render with a "loading…"
  // placeholder if this fetch is still in flight by the time the
  // project list arrives. Failures keep the empty default so the
  // dashboard never blocks the rest of the projects view.
  statsLoading.value = true
  try {
    const data = await wrapsApi.getAllStats()
    const rows = Array.isArray(data?.stats) ? data.stats : []
    const next = {}
    for (const row of rows) {
      next[row.projectId] = row
    }
    memoryByProject.value = next
  } catch (_err) {
    memoryByProject.value = {}
  } finally {
    statsLoading.value = false
  }
}

function memoryForProject(projectId) {
  return (
    memoryByProject.value[projectId] || {
      wrapCount: 0,
      memorySizeBytes: 0,
      lastWrappedAt: null
    }
  )
}

function formatLastWrapped(iso) {
  if (!iso) return 'Never'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    // Date-only is enough for the dashboard ("2026-05-13").
    // We deliberately don't use locale strings here so the
    // ISO-ish format reads the same on every machine.
    return d.toISOString().slice(0, 10)
  } catch (_e) {
    return iso
  }
}

function memoryTooltip(projectId) {
  const m = memoryForProject(projectId)
  if (!m.wrapCount) return 'No wraps saved for this project yet.'
  return `${m.wrapCount} wraps · ${formatBytes(m.memorySizeBytes)} on disk`
}

function openCreate() {
  editingProject.value = null
  dialogOpen.value = true
}

function openEdit(project) {
  editingProject.value = { ...project }
  dialogOpen.value = true
}

function closeDialog() {
  dialogOpen.value = false
  editingProject.value = null
}

function onCreated(project) {
  projects.value = [project, ...projects.value]
  closeDialog()
}

function onUpdated(project) {
  const idx = projects.value.findIndex((p) => p.id === project.id)
  if (idx !== -1) projects.value.splice(idx, 1, project)
  // re-sort by updated_at desc
  projects.value = [...projects.value].sort((a, b) =>
    (b.updated_at || '').localeCompare(a.updated_at || '')
  )
  closeDialog()
}

async function onDelete(project) {
  const ok = window.confirm(
    `Delete "${project.name}"? Blablas and Context Packs in this project will be removed in later milestones.`
  )
  if (!ok) return
  deletingId.value = project.id
  try {
    await projectsApi.remove(project.id)
    projects.value = projects.value.filter((p) => p.id !== project.id)
  } catch (err) {
    loadError.value = describeApiError(err, 'Could not delete the project.')
  } finally {
    deletingId.value = null
  }
}

onMounted(() => {
  loadProjects()
  loadMemoryStats()
})
</script>

<style scoped>
.projects-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.projects-view__loading {
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
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
  align-items: center;
}

.banner--error {
  background: rgba(198, 40, 40, 0.06);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.banner strong {
  font-weight: 600;
}

.project-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.project-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}

.project-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-2, 0 4px 14px rgba(0, 0, 0, 0.08));
}

.project-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-2);
}

.project-card__name-link {
  flex: 1;
  min-width: 0;
  text-decoration: none;
  color: inherit;
  border-radius: var(--radius-sm);
}

.project-card__name-link:hover .project-card__name {
  color: var(--color-primary);
  text-decoration: underline;
}

.project-card__name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.3;
  word-break: break-word;
}

.project-card__menu {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.icon-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--color-text-muted);
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.icon-btn:hover:not(:disabled) {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.icon-btn--danger:hover:not(:disabled) {
  background: rgba(198, 40, 40, 0.08);
  color: #c62828;
}

.icon-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.project-card__description {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: calc(var(--text-sm) * 1.5 * 2);
}

.project-card__memory {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  line-height: 1.4;
}

.project-card__memory--empty {
  color: var(--color-text-muted);
}

.project-card__memory-icon {
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.project-card__memory-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.project-card__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
}

.project-card__time {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
