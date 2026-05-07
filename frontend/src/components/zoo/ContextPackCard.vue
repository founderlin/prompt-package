<template>
  <article class="pack-card" :class="{ 'pack-card--deleting': deleting }">
    <!-- Whole-card link so the user can click anywhere non-interactive
         to go to the detail page. Action buttons on top of this use
         @click.stop to avoid double-navigation. -->
    <RouterLink
      :to="detailRoute"
      class="pack-card__link"
      :aria-label="`Open ${pack.title || 'Context Pack'}`"
    />

    <header class="pack-card__header">
      <div class="pack-card__title-row">
        <h3 class="pack-card__title">{{ pack.title || 'Untitled pack' }}</h3>
        <div class="pack-card__type-chips" aria-label="Content types">
          <span
            v-for="tag in contentTypes"
            :key="tag"
            class="chip pack-card__type-chip"
            :class="{
              'chip--success': tag === 'Graph',
              'chip--warning': tag === 'Vector'
            }"
          >
            {{ tag }}
          </span>
        </div>
      </div>
      <p v-if="pack.description" class="pack-card__description">
        {{ pack.description }}
      </p>
    </header>

    <p v-if="summaryPreview" class="pack-card__summary">{{ summaryPreview }}</p>
    <p v-else class="pack-card__summary pack-card__summary--muted">
      No summary yet.
    </p>

    <ul
      v-if="pack.keywords && pack.keywords.length"
      class="pack-card__keywords"
      aria-label="Keywords"
    >
      <li
        v-for="(kw, idx) in pack.keywords.slice(0, MAX_KEYWORDS)"
        :key="idx"
        class="chip chip--primary pack-card__keyword"
      >
        {{ kw }}
      </li>
      <li
        v-if="pack.keywords.length > MAX_KEYWORDS"
        class="pack-card__keyword-more"
      >
        +{{ pack.keywords.length - MAX_KEYWORDS }}
      </li>
    </ul>

    <dl class="pack-card__meta">
      <div class="pack-card__meta-item">
        <dt>Source</dt>
        <dd>
          <span
            class="chip pack-card__source-chip"
            :class="sourceChipClass"
          >
            {{ sourceLabel }}
          </span>
          <span v-if="sourceCountLabel" class="pack-card__meta-hint">
            · {{ sourceCountLabel }}
          </span>
        </dd>
      </div>
      <div class="pack-card__meta-item">
        <dt>Created</dt>
        <dd :title="createdAtTitle">{{ createdAtRelative }}</dd>
      </div>
      <div class="pack-card__meta-item">
        <dt>Last used</dt>
        <dd :title="lastUsedTitle">{{ lastUsedRelative }}</dd>
      </div>
      <div class="pack-card__meta-item">
        <dt>Uses</dt>
        <dd>{{ pack.usage_count || 0 }}</dd>
      </div>
    </dl>

    <footer class="pack-card__footer">
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        :disabled="deleting"
        @click.stop="emit('delete', pack)"
      >
        Delete
      </button>
      <RouterLink
        :to="detailRoute"
        class="btn btn--primary btn--sm pack-card__cta"
        @click.stop
      >
        Open
      </RouterLink>
    </footer>
  </article>
</template>

<script setup>
/**
 * A single Context Pack card used in the Context Zoo grid.
 *
 * Displays (per spec):
 *   - title, description, summary preview
 *   - keywords as chips
 *   - source type (color-coded)
 *   - rough source count (memory_count when available)
 *   - created / last-used relative timestamps with absolute on hover
 *   - usage_count
 *   - content-type tags (Text / Graph / Vector) via the contentTypes
 *     utility — always includes 'Text' so legacy packs still show one.
 *
 * This component only *emits* destructive actions; it never mutates
 * the pack itself. Parents (ContextZooView) drive state changes so
 * the list can optimistic-update, handle errors centrally, and
 * coordinate the confirm dialog.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import {
  contentTypesForPack,
  sourceTypeChipVariant,
  sourceTypeLabel
} from '@/utils/contentTypes'
import { formatDateTime, relativeTime } from '@/utils/time'

const props = defineProps({
  pack: { type: Object, required: true },
  /** When true, renders the card in a muted / disabled state — used
   *  while the delete request is in flight so the parent can keep
   *  the row visible without mis-clicks. */
  deleting: { type: Boolean, default: false }
})

const emit = defineEmits(['delete'])

const MAX_KEYWORDS = 4
const SUMMARY_PREVIEW_CHARS = 180

const detailRoute = computed(() => ({
  name: 'context-zoo-detail',
  params: { contextPackId: String(props.pack.id) }
}))

const contentTypes = computed(() => contentTypesForPack(props.pack))

const sourceLabel = computed(() => sourceTypeLabel(props.pack.source_type))

const sourceChipClass = computed(() => {
  const variant = sourceTypeChipVariant(props.pack.source_type)
  return variant ? `chip--${variant}` : ''
})

// Prefer explicit memory_count when present; otherwise fall back to
// source_memory_ids length. Both are exposed by the list endpoint.
const sourceCountLabel = computed(() => {
  const pack = props.pack
  const count =
    typeof pack.memory_count === 'number' && pack.memory_count > 0
      ? pack.memory_count
      : Array.isArray(pack.source_memory_ids)
        ? pack.source_memory_ids.length
        : 0
  if (count <= 0) return ''
  const noun =
    pack.source_type === 'project'
      ? pluralize(count, 'memory', 'memories')
      : pluralize(count, 'message', 'messages')
  return `${count} ${noun}`
})

const summaryPreview = computed(() => {
  const raw = (props.pack.summary || '').trim()
  if (!raw) {
    // Fall back to body_preview that the list endpoint provides.
    const body = (props.pack.body_preview || '').trim()
    if (!body) return ''
    return clip(body, SUMMARY_PREVIEW_CHARS)
  }
  return clip(raw, SUMMARY_PREVIEW_CHARS)
})

const createdAtRelative = computed(() =>
  props.pack.created_at ? relativeTime(props.pack.created_at) : '—'
)
const createdAtTitle = computed(() =>
  props.pack.created_at ? formatDateTime(props.pack.created_at) : ''
)

const lastUsedRelative = computed(() =>
  props.pack.last_used_at ? relativeTime(props.pack.last_used_at) : 'Never'
)
const lastUsedTitle = computed(() =>
  props.pack.last_used_at ? formatDateTime(props.pack.last_used_at) : ''
)

function clip(text, max) {
  if (!text) return ''
  if (text.length <= max) return text
  return text.slice(0, max - 1).trimEnd() + '…'
}

function pluralize(count, singular, plural) {
  return count === 1 ? singular : plural
}
</script>

<style scoped>
.pack-card {
  position: relative;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 260px;
  transition: box-shadow 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.pack-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-2, 0 4px 14px rgba(0, 0, 0, 0.08));
}

.pack-card--deleting {
  opacity: 0.55;
  pointer-events: none;
}

/* Invisible anchor filling the entire card so anywhere non-interactive
   becomes a click target for the detail route. z-index:0 keeps it
   *under* the interactive buttons, which sit at z-index:1 via
   .pack-card__footer > * and .pack-card__keyword positioning. */
.pack-card__link {
  position: absolute;
  inset: 0;
  z-index: 0;
  border-radius: inherit;
  text-decoration: none;
  /* Screen-reader-only label; no visible content. */
}

.pack-card__link:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}

.pack-card > *:not(.pack-card__link) {
  position: relative;
  z-index: 1;
}

.pack-card__header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pack-card__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.pack-card__title {
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--color-text-primary);
  margin: 0;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.pack-card__type-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex-shrink: 0;
}

.pack-card__type-chip {
  font-size: 10px;
  padding: 2px 8px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.pack-card__description {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pack-card__summary {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.pack-card__summary--muted {
  color: var(--color-text-muted);
  font-style: italic;
}

.pack-card__keywords {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.pack-card__keyword {
  font-size: var(--text-xs);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pack-card__keyword-more {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  padding: 2px 6px;
  align-self: center;
}

.pack-card__meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2) var(--space-3);
  margin: 0;
  padding-top: var(--space-2);
  border-top: 1px solid var(--color-border);
}

.pack-card__meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.pack-card__meta-item dt {
  font-size: 10px;
  font-weight: 500;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.pack-card__meta-item dd {
  font-size: var(--text-xs);
  color: var(--color-text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.pack-card__meta-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.pack-card__source-chip {
  font-size: 10px;
  padding: 2px 8px;
  font-weight: 500;
}

.pack-card__footer {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: var(--space-2);
  padding-top: var(--space-2);
}

.pack-card__cta {
  text-decoration: none;
}
</style>
