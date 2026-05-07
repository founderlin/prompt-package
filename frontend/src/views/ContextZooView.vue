<template>
  <div class="zoo-view">
    <PageHeader
      title="Context Zoo"
      description="Browse, search, and reuse every Context Pack you've created."
    >
      <template #actions>
        <RouterLink to="/projects" class="btn btn--ghost">
          Open a project
        </RouterLink>
      </template>
    </PageHeader>

    <!-- Toolbar: search + source-type filter + project filter + sort -->
    <section class="zoo-toolbar" role="region" aria-label="Filters">
      <label class="zoo-toolbar__search" :class="{ 'is-focused': searchFocused }">
        <span class="zoo-toolbar__label-text">Search</span>
        <span class="zoo-toolbar__search-field">
          <svg
            class="zoo-toolbar__search-icon"
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
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            v-model="searchInput"
            type="search"
            class="input zoo-toolbar__search-input"
            placeholder="Search title, description, keywords…"
            aria-label="Search Context Packs"
            @focus="searchFocused = true"
            @blur="searchFocused = false"
          />
          <button
            v-if="searchInput"
            type="button"
            class="zoo-toolbar__clear"
            aria-label="Clear search"
            @click="clearSearch"
          >
            ×
          </button>
        </span>
      </label>

      <div class="zoo-toolbar__group">
        <label class="zoo-toolbar__label">
          <span class="zoo-toolbar__label-text">Source</span>
          <select v-model="sourceTypeFilter" class="select">
            <option value="">All</option>
            <option v-for="opt in SOURCE_OPTIONS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </label>

        <label class="zoo-toolbar__label">
          <span class="zoo-toolbar__label-text">Project</span>
          <select v-model="projectFilter" class="select" :disabled="!projects.length">
            <option value="">All</option>
            <option
              v-for="p in projects"
              :key="p.id"
              :value="String(p.id)"
            >
              {{ p.name }}
            </option>
          </select>
        </label>

        <label class="zoo-toolbar__label">
          <span class="zoo-toolbar__label-text">Sort</span>
          <select v-model="sortKey" class="select">
            <option value="created_desc">Newest</option>
            <option value="created_asc">Oldest</option>
            <option value="last_used_desc">Recently used</option>
            <option value="last_used_asc">Least recently used</option>
          </select>
        </label>
      </div>
    </section>

    <!-- Result meta: total + active-filter chips -->
    <div class="zoo-result-row" v-if="!loading || total != null">
      <p class="zoo-result-row__total">
        <template v-if="total === 1">1 pack</template>
        <template v-else>{{ total ?? 0 }} packs</template>
        <template v-if="filterActive">
          · filtered
          <button
            type="button"
            class="zoo-result-row__reset"
            @click="resetFilters"
          >
            Reset
          </button>
        </template>
      </p>
    </div>

    <!-- LOADING -->
    <div v-if="loading && !packs.length" class="zoo-state">
      <span class="spinner" aria-hidden="true" />
      <span class="text-secondary">Loading Context Packs…</span>
    </div>

    <!-- ERROR -->
    <div
      v-else-if="loadError"
      class="banner banner--error"
      role="alert"
    >
      <strong>Could not load Context Packs.</strong>
      <span>{{ loadError }}</span>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        @click="loadPacks"
      >
        Retry
      </button>
    </div>

    <!-- EMPTY — no packs at all (no filters active) -->
    <EmptyState
      v-else-if="!packs.length && !filterActive"
      title="No Context Packs yet"
      description="Wrap up a conversation or a whole project to create your first pack. Then it'll show up here, ready to reuse in any new chat."
    >
      <template #actions>
        <RouterLink to="/projects" class="btn btn--primary">
          Open a project to start
        </RouterLink>
      </template>
    </EmptyState>

    <!-- EMPTY — filters matched nothing -->
    <EmptyState
      v-else-if="!packs.length && filterActive"
      compact
      title="No packs match your filters"
      description="Try a different search or clear the filters."
    >
      <template #actions>
        <button class="btn btn--ghost btn--sm" @click="resetFilters">
          Reset filters
        </button>
      </template>
    </EmptyState>

    <!-- GRID -->
    <section v-else class="zoo-grid" aria-label="Context Packs">
      <ContextPackCard
        v-for="pack in packs"
        :key="pack.id"
        :pack="pack"
        :deleting="deletingId === pack.id"
        @delete="onDeleteRequest"
      />
    </section>

    <!-- PAGINATION -->
    <nav
      v-if="packs.length && (hasPrev || hasNext)"
      class="zoo-pagination"
      aria-label="Pagination"
    >
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="!hasPrev || loading"
        @click="prevPage"
      >
        ← Previous
      </button>
      <span class="zoo-pagination__info">
        Page {{ currentPage }} of {{ pageCount }}
      </span>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="!hasNext || loading"
        @click="nextPage"
      >
        Next →
      </button>
    </nav>

    <!-- Confirm-delete -->
    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :message="confirmMessage"
      confirm-label="Delete"
      busy-label="Deleting…"
      tone="danger"
      :busy="confirmBusy"
      @confirm="onConfirmDelete"
      @cancel="onCancelDelete"
    />
  </div>
</template>

<script setup>
/**
 * ContextZooView — the flat, searchable, filterable, paginated grid of
 * every Context Pack the current user owns.
 *
 * Design choices:
 *
 * 1. **All state is URL-hydrated on mount.** Search / filter / sort /
 *    page are read from query params so deep-links survive reloads and
 *    the browser back button works intuitively. Changes are debounced
 *    and pushed via router.replace to avoid spamming history.
 *
 * 2. **Search + filter + sort happen server-side** via the API's
 *    ``keyword / projectId / sourceType / limit / offset`` params.
 *    Sorting that the backend doesn't expose (last_used_*) is applied
 *    *after* fetch on the current page — acceptable as long as the
 *    page size is bounded. (Adding backend sort would require
 *    service-layer work — not needed for MVP and kept as a clear
 *    future extension point.)
 *
 * 3. **Delete uses the shared ConfirmDialog** rather than window.confirm
 *    to match the Zoo's polished look and to standardize destructive
 *    flows across the app.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ContextPackCard from '@/components/zoo/ContextPackCard.vue'
import contextPacksApi from '@/api/contextPacks'
import projectsApi from '@/api/projects'
import { useToasts } from '@/stores/toasts'
import { describeApiError } from '@/utils/errors'

const PAGE_SIZE = 24
const DEBOUNCE_MS = 300

const SOURCE_OPTIONS = [
  { value: 'project', label: 'Project' },
  { value: 'conversation', label: 'Conversation' },
  { value: 'note', label: 'Note' },
  { value: 'attachment', label: 'Attachment' },
  { value: 'mixed', label: 'Mixed' }
]

const route = useRoute()
const router = useRouter()
const toasts = useToasts()

// ---- Toolbar state --------------------------------------------------
const searchInput = ref('') // raw input (live)
const searchFocused = ref(false)
const keyword = ref('') // debounced, drives the API
const sourceTypeFilter = ref('')
const projectFilter = ref('') // string id
const sortKey = ref('created_desc')
const page = ref(1)

// ---- Data -----------------------------------------------------------
const packs = ref([])
const total = ref(null)
const loading = ref(false)
const loadError = ref('')
const projects = ref([])

// ---- Delete flow ----------------------------------------------------
const confirmOpen = ref(false)
const confirmBusy = ref(false)
const packToDelete = ref(null)
const deletingId = ref(null)

const confirmTitle = computed(() =>
  packToDelete.value
    ? `Delete "${packToDelete.value.title || 'Context Pack'}"?`
    : 'Delete Context Pack?'
)
const confirmMessage = computed(
  () =>
    'This removes the pack and its source references. This action cannot be undone.'
)

// ---- Derived -------------------------------------------------------
const filterActive = computed(
  () =>
    !!keyword.value ||
    !!sourceTypeFilter.value ||
    !!projectFilter.value
)

const pageCount = computed(() => {
  if (total.value == null) return 1
  return Math.max(1, Math.ceil(total.value / PAGE_SIZE))
})
const currentPage = computed(() => page.value)
const hasPrev = computed(() => page.value > 1)
const hasNext = computed(() => page.value < pageCount.value)

// ---- URL <-> state hydration ---------------------------------------
// On mount we read the query; from then on, changes to the filter
// state push into the URL via router.replace so reloads preserve
// exact scroll position for the user.

function readFromQuery() {
  const q = route.query || {}
  searchInput.value = typeof q.q === 'string' ? q.q : ''
  keyword.value = searchInput.value
  sourceTypeFilter.value =
    typeof q.sourceType === 'string' ? q.sourceType : ''
  projectFilter.value =
    typeof q.projectId === 'string' ? q.projectId : ''
  sortKey.value = typeof q.sort === 'string' ? q.sort : 'created_desc'
  const p = parseInt(q.page, 10)
  page.value = Number.isFinite(p) && p > 0 ? p : 1
}

function pushToQuery() {
  const next = {}
  if (keyword.value) next.q = keyword.value
  if (sourceTypeFilter.value) next.sourceType = sourceTypeFilter.value
  if (projectFilter.value) next.projectId = projectFilter.value
  if (sortKey.value && sortKey.value !== 'created_desc') next.sort = sortKey.value
  if (page.value > 1) next.page = String(page.value)
  // Avoid redundant navigations — router.replace re-fires watchers.
  if (shallowEqual(next, route.query)) return
  router.replace({ name: 'context-zoo', query: next })
}

function shallowEqual(a, b) {
  const ak = Object.keys(a)
  const bk = Object.keys(b)
  if (ak.length !== bk.length) return false
  for (const k of ak) {
    if (a[k] !== b[k]) return false
  }
  return true
}

// ---- Debounced keyword hydration -----------------------------------
let debounceTimer = null
watch(searchInput, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    if (keyword.value !== val.trim()) {
      keyword.value = val.trim()
      page.value = 1
    }
  }, DEBOUNCE_MS)
})

function clearSearch() {
  searchInput.value = ''
  keyword.value = ''
  page.value = 1
}

// Re-fetch when any real filter / page changes.
watch(
  [keyword, sourceTypeFilter, projectFilter, sortKey, page],
  () => {
    pushToQuery()
    loadPacks()
  }
)

// Filter-change side-effect: reset to page 1. (We watch `page`
// separately above; guarding here avoids an infinite loop.)
watch([sourceTypeFilter, projectFilter, sortKey], () => {
  if (page.value !== 1) {
    page.value = 1
  }
})

function resetFilters() {
  searchInput.value = ''
  keyword.value = ''
  sourceTypeFilter.value = ''
  projectFilter.value = ''
  sortKey.value = 'created_desc'
  page.value = 1
}

// ---- Fetching ------------------------------------------------------
async function loadPacks() {
  loading.value = true
  loadError.value = ''
  try {
    const offset = (page.value - 1) * PAGE_SIZE
    const resp = await contextPacksApi.list({
      keyword: keyword.value || undefined,
      sourceType: sourceTypeFilter.value || undefined,
      projectId: projectFilter.value || undefined,
      limit: PAGE_SIZE,
      offset
    })
    const items = Array.isArray(resp?.items)
      ? resp.items
      : Array.isArray(resp?.context_packs)
        ? resp.context_packs
        : []
    packs.value = applyClientSort(items, sortKey.value)
    total.value = typeof resp?.total === 'number' ? resp.total : items.length
  } catch (err) {
    loadError.value = describeApiError(err, 'Could not load Context Packs.')
  } finally {
    loading.value = false
  }
}

function applyClientSort(items, key) {
  // Server already orders by created_at desc; re-sort only when the
  // user picked something else. Copy first so we don't mutate the
  // incoming array reference.
  const out = [...items]
  switch (key) {
    case 'created_asc':
      out.sort((a, b) => cmpDate(a.created_at, b.created_at))
      break
    case 'last_used_desc':
      out.sort((a, b) => cmpDate(b.last_used_at, a.last_used_at))
      break
    case 'last_used_asc':
      out.sort((a, b) => cmpDate(a.last_used_at, b.last_used_at))
      break
    case 'created_desc':
    default:
      out.sort((a, b) => cmpDate(b.created_at, a.created_at))
      break
  }
  return out
}

function cmpDate(a, b) {
  // null / undefined sort last (largest).
  const ta = a ? Date.parse(a) : Number.POSITIVE_INFINITY
  const tb = b ? Date.parse(b) : Number.POSITIVE_INFINITY
  return ta - tb
}

async function loadProjects() {
  // Best-effort — failure here just hides the project filter dropdown
  // but doesn't break the zoo.
  try {
    const data = await projectsApi.list()
    projects.value = Array.isArray(data?.projects) ? data.projects : []
  } catch (_err) {
    projects.value = []
  }
}

// ---- Delete flow ---------------------------------------------------

function onDeleteRequest(pack) {
  packToDelete.value = pack
  confirmOpen.value = true
}

function onCancelDelete() {
  if (confirmBusy.value) return
  confirmOpen.value = false
  packToDelete.value = null
}

async function onConfirmDelete() {
  const pack = packToDelete.value
  if (!pack || confirmBusy.value) return
  confirmBusy.value = true
  deletingId.value = pack.id
  try {
    await contextPacksApi.remove(pack.id)
    // Optimistic local removal. If this was the last item on a page,
    // step back one page and re-fetch so we don't leave the user on
    // an empty page. Otherwise re-fetch the same page (keeps totals
    // in sync).
    packs.value = packs.value.filter((p) => p.id !== pack.id)
    total.value = Math.max(0, (total.value ?? 1) - 1)
    confirmOpen.value = false
    packToDelete.value = null
    toasts.push({
      kind: 'success',
      message: `Deleted "${pack.title || 'Context Pack'}".`
    })
    if (packs.value.length === 0 && page.value > 1) {
      page.value -= 1
    } else {
      loadPacks()
    }
  } catch (err) {
    toasts.push({
      kind: 'error',
      message: describeApiError(err, 'Could not delete this pack.')
    })
  } finally {
    confirmBusy.value = false
    deletingId.value = null
  }
}

// ---- Pagination controls -------------------------------------------
function prevPage() {
  if (hasPrev.value) page.value -= 1
}
function nextPage() {
  if (hasNext.value) page.value += 1
}

// ---- Lifecycle -----------------------------------------------------
onMounted(async () => {
  readFromQuery()
  await Promise.all([loadProjects(), loadPacks()])
})
</script>

<style scoped>
.zoo-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ---- Toolbar ------------------------------------------------------ */

.zoo-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
}

.zoo-toolbar__search {
  /* Mirror the Source / Project / Sort dropdowns: small uppercase
     caption on top, control below. ``position: relative`` is moved
     to ``.zoo-toolbar__search-field`` so the icon + clear button
     position against the input, not the whole label. */
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1 1 280px;
  min-width: 240px;
  max-width: 520px;
}

.zoo-toolbar__search-field {
  position: relative;
  display: block;
}

.zoo-toolbar__search-input {
  width: 100%;
  padding-left: 36px;
  padding-right: 32px;
}

.zoo-toolbar__search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  pointer-events: none;
}

.zoo-toolbar__search.is-focused .zoo-toolbar__search-icon {
  color: var(--color-primary);
}

.zoo-toolbar__clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: transparent;
  font-size: 18px;
  line-height: 1;
  color: var(--color-text-muted);
  width: 22px;
  height: 22px;
  border-radius: 50%;
  cursor: pointer;
}

.zoo-toolbar__clear:hover {
  background: var(--color-surface-muted);
  color: var(--color-text-primary);
}

.zoo-toolbar__group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: flex-end;
}

.zoo-toolbar__label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 140px;
}

.zoo-toolbar__label-text {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-muted);
}

/* ---- Result row --------------------------------------------------- */

.zoo-result-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  font-size: var(--text-sm);
}

.zoo-result-row__total {
  margin: 0;
  color: var(--color-text-secondary);
}

.zoo-result-row__reset {
  margin-left: var(--space-2);
  background: none;
  border: none;
  padding: 0;
  color: var(--color-primary);
  cursor: pointer;
  font-size: inherit;
}

.zoo-result-row__reset:hover {
  text-decoration: underline;
}

/* ---- States ------------------------------------------------------- */

.zoo-state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-5);
  justify-content: center;
}

.banner {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.banner--error {
  background: var(--color-error-soft);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

/* ---- Grid --------------------------------------------------------- */

.zoo-grid {
  display: grid;
  /* Responsive by construction:
     - desktop (>=1120px, inside content-max 1440): fits 4 columns
     - medium (~900px): 3 columns
     - tablet (~620px): 2 columns
     - mobile: 1 column
     auto-fill + minmax does all of this without media queries.     */
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

/* ---- Pagination --------------------------------------------------- */

.zoo-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0 var(--space-5);
}

.zoo-pagination__info {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  min-width: 120px;
  text-align: center;
}

@media (max-width: 520px) {
  .zoo-toolbar__label {
    min-width: 0;
    flex: 1 1 120px;
  }
}
</style>
