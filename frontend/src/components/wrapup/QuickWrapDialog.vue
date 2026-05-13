<template>
  <Teleport to="body">
    <transition name="dialog">
      <div
        v-if="open"
        class="dialog-backdrop"
        role="presentation"
        @mousedown.self="onBackdrop"
      >
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
        >
          <header class="dialog__header">
            <h2 :id="titleId" class="dialog__title">
              {{ headerTitle }}
            </h2>
            <button
              class="dialog__close"
              type="button"
              :disabled="phase === 'drafting' || phase === 'saving'"
              aria-label="Close"
              @click="onCancel"
            >
              ×
            </button>
          </header>

          <!-- DRAFTING (loading) -->
          <div
            v-if="phase === 'drafting'"
            class="dialog__body dialog__body--progress"
          >
            <div class="quickwrap-progress">
              <span class="spinner spinner--lg" aria-hidden="true" />
              <h3 class="quickwrap-progress__label">Generating wrap draft…</h3>
              <p class="quickwrap-progress__hint">
                Using <code>{{ defaultModel }}</code> · default filters.
              </p>
            </div>
          </div>

          <!-- PREVIEW -->
          <div
            v-else-if="phase === 'preview' || phase === 'saving'"
            class="dialog__body"
          >
            <p v-if="draft?.usedMock" class="banner banner--info" role="status">
              <strong>Mock wrap.</strong>
              <span>
                No provider key on file — install one in Settings to get
                LLM-generated wraps.
              </span>
            </p>

            <section class="quickwrap-meta">
              <div class="quickwrap-meta__row">
                <span class="quickwrap-meta__label">Title</span>
                <span class="quickwrap-meta__value">
                  {{ draft?.analysis?.title || '—' }}
                </span>
              </div>
              <div class="quickwrap-meta__row">
                <span class="quickwrap-meta__label">Topic</span>
                <span class="quickwrap-meta__value">
                  {{ draft?.analysis?.topic || '—' }}
                </span>
              </div>
              <div class="quickwrap-meta__row">
                <span class="quickwrap-meta__label">Save path</span>
                <code class="quickwrap-meta__path">
                  {{ draft?.savePathRelative || '—' }}
                </code>
              </div>
            </section>

            <section v-if="draft?.analysis?.summary" class="quickwrap-section">
              <h4 class="quickwrap-section__title">Summary</h4>
              <p class="quickwrap-section__text">
                {{ draft.analysis.summary }}
              </p>
            </section>

            <section
              v-if="draft?.analysis?.tags && draft.analysis.tags.length"
              class="quickwrap-section"
            >
              <h4 class="quickwrap-section__title">Tags</h4>
              <ul class="quickwrap-tags">
                <li
                  v-for="t in draft.analysis.tags"
                  :key="t"
                  class="quickwrap-tag"
                >
                  {{ t }}
                </li>
              </ul>
            </section>

            <section class="quickwrap-section">
              <h4 class="quickwrap-section__title">Markdown preview</h4>
              <pre class="quickwrap-markdown">{{ truncatedMarkdown }}</pre>
              <p v-if="markdownTruncated" class="quickwrap-section__hint">
                Showing first {{ PREVIEW_CHARS }} characters of
                {{ draft?.markdown?.length || 0 }} — full content will be
                written on save.
              </p>
            </section>

            <footer class="dialog__actions">
              <button
                type="button"
                class="btn btn--ghost"
                :disabled="phase === 'saving'"
                @click="onCancel"
              >
                Cancel
              </button>
              <button
                type="button"
                class="btn btn--ghost"
                :title="ADVANCED_TODO_HINT"
                disabled
              >
                Edit in Advanced
              </button>
              <button
                type="button"
                class="btn btn--primary"
                :disabled="!draft || phase === 'saving'"
                @click="onSave"
              >
                <span v-if="phase === 'saving'" class="spinner" aria-hidden="true" />
                <span>{{ phase === 'saving' ? 'Saving…' : 'Save' }}</span>
              </button>
            </footer>
          </div>

          <!-- FAILED (either drafting or saving) -->
          <div v-else-if="phase === 'failed'" class="dialog__body">
            <div class="banner banner--error" role="alert">
              <strong>{{ failedHeading }}</strong>
              <span>{{ errorMessage }}</span>
            </div>
            <footer class="dialog__actions">
              <button
                type="button"
                class="btn btn--ghost"
                @click="onCancel"
              >
                Close
              </button>
              <button
                type="button"
                class="btn btn--primary"
                @click="onRetry"
              >
                Try again
              </button>
            </footer>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * QuickWrapDialog
 *
 * Drives the Quick Wrap user flow:
 *
 *   open → drafting → preview → saving → close (toast)
 *                  ↘ failed (retry)        ↘ failed (retry)
 *
 * Props:
 *   open             : boolean       — controls visibility (v-model:open)
 *   projectId        : number|string — required
 *   conversationId   : number|string — required
 *
 * Events:
 *   update:open      — for v-model:open
 *   close            — user dismissed the dialog
 *   saved(wrap)      — wrap was persisted; payload is the SavedWrap object
 *
 * Loading / error states are owned internally, so the parent only has
 * to mount the dialog and wait for the ``saved`` event to show its
 * own toast.
 */
import { computed, nextTick, ref, watch } from 'vue'
import wrapsApi from '@/api/wraps'
import { describeApiError } from '@/utils/errors'

const PREVIEW_CHARS = 1200
// Phase 4: a dedicated Advanced Wrap dialog lives on the menu now.
// We deliberately don't open it from here — switching mid-preview
// would discard the Quick draft. The button stays disabled with a
// hint pointing at the menu.
const ADVANCED_TODO_HINT =
  'Open Advanced Wrap from the Wrap menu to choose model, edit filters, and review Markdown.'

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: [Number, String], default: null },
  conversationId: { type: [Number, String], default: null }
})

const emit = defineEmits(['update:open', 'close', 'saved'])

const titleId = `quick-wrap-title-${Math.random().toString(36).slice(2, 8)}`

// 'idle' | 'drafting' | 'preview' | 'saving' | 'failed'
const phase = ref('idle')
const draft = ref(null)
const errorMessage = ref('')
const errorFrom = ref('') // 'drafting' | 'saving'

// Default model surfaced in the loading hint + sent in the request.
// Reads the user-tunable preference from Settings → Wrap model
// (localStorage); falls back to ``deepseek-v4-flash`` when unset.
import { getDefaultWrapModel } from '@/utils/wrapModelPref'
const defaultModel = ref(getDefaultWrapModel())

const headerTitle = computed(() => {
  switch (phase.value) {
    case 'drafting':
      return 'Quick Wrap'
    case 'preview':
      return 'Quick Wrap · preview'
    case 'saving':
      return 'Saving wrap…'
    case 'failed':
      return errorFrom.value === 'saving' ? 'Save failed' : 'Wrap failed'
    default:
      return 'Quick Wrap'
  }
})

const failedHeading = computed(() => {
  return errorFrom.value === 'saving'
    ? 'Could not save the wrap.'
    : 'Could not generate the wrap.'
})

const truncatedMarkdown = computed(() => {
  const md = draft.value?.markdown || ''
  if (md.length <= PREVIEW_CHARS) return md
  return md.slice(0, PREVIEW_CHARS).trimEnd() + '\n…'
})

const markdownTruncated = computed(() => {
  return (draft.value?.markdown || '').length > PREVIEW_CHARS
})

watch(
  () => props.open,
  async (next) => {
    if (next) {
      // Fresh state for every open — no stale draft from a prior session.
      phase.value = 'idle'
      draft.value = null
      errorMessage.value = ''
      errorFrom.value = ''
      await nextTick()
      runDraft()
    }
  },
  { immediate: false }
)

async function runDraft() {
  phase.value = 'drafting'
  errorMessage.value = ''
  errorFrom.value = ''
  try {
    // Refresh the preference each time the dialog opens — the user
    // could have flipped it in Settings since the previous draft.
    defaultModel.value = getDefaultWrapModel()
    const data = await wrapsApi.draftQuick(
      props.projectId,
      props.conversationId,
      { model: defaultModel.value }
    )
    draft.value = data?.draft || null
    if (!draft.value) {
      throw new Error('Server returned no draft payload.')
    }
    phase.value = 'preview'
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not generate wrap draft.')
    errorFrom.value = 'drafting'
    phase.value = 'failed'
  }
}

async function onSave() {
  if (!draft.value) return
  phase.value = 'saving'
  errorMessage.value = ''
  try {
    const data = await wrapsApi.save(props.projectId, {
      markdown: draft.value.markdown,
      filename: draft.value.suggestedFilename
    })
    emit('saved', data?.wrap || null)
    closeDialog()
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not save wrap.')
    errorFrom.value = 'saving'
    phase.value = 'failed'
  }
}

function onRetry() {
  if (errorFrom.value === 'saving') {
    phase.value = 'preview'
  } else {
    runDraft()
  }
}

function onBackdrop() {
  if (phase.value === 'drafting' || phase.value === 'saving') return
  closeDialog()
}

function onCancel() {
  if (phase.value === 'drafting' || phase.value === 'saving') return
  closeDialog()
}

function closeDialog() {
  emit('update:open', false)
  emit('close')
}
</script>

<style scoped>
/* Reuses the layout primitives from WrapUpDialog.vue so the two dialogs
   visually match. We deliberately keep the CSS local (not shared) to
   avoid coupling future style changes. */

.dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--space-4);
}

.dialog {
  background: var(--color-surface);
  width: min(720px, 100%);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-3, 0 20px 50px rgba(0, 0, 0, 0.18));
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - var(--space-6));
  overflow: hidden;
}

.dialog__header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.dialog__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 500;
}

.dialog__close {
  background: transparent;
  border: none;
  font-size: 24px;
  line-height: 1;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
}

.dialog__close:hover:not(:disabled) {
  background: var(--color-surface-muted);
  color: var(--color-text-primary);
}

.dialog__close:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.dialog__body {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  overflow: auto;
}

.dialog__body--progress {
  min-height: 240px;
  align-items: center;
  justify-content: center;
}

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.banner {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.banner--info {
  background: var(--color-surface-muted);
}

.banner--error {
  background: rgba(198, 40, 40, 0.06);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.quickwrap-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  text-align: center;
}

.quickwrap-progress__label {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 500;
}

.quickwrap-progress__hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.quickwrap-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  background: var(--color-surface-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.quickwrap-meta__row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.quickwrap-meta__label {
  flex-shrink: 0;
  width: 88px;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.quickwrap-meta__value {
  font-weight: 500;
  color: var(--color-text-primary);
  word-break: break-word;
}

.quickwrap-meta__path {
  font-size: var(--text-xs);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  word-break: break-all;
}

.quickwrap-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quickwrap-section__title {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.quickwrap-section__text {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  white-space: pre-wrap;
}

.quickwrap-section__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-style: italic;
}

.quickwrap-tags {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.quickwrap-tag {
  font-size: var(--text-xs);
  padding: 3px 8px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: 999px;
}

.quickwrap-markdown {
  margin: 0;
  font-size: var(--text-xs);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
  max-height: 280px;
  overflow: auto;
}

.dialog-enter-active,
.dialog-leave-active {
  transition: opacity 0.15s ease;
}
.dialog-enter-active .dialog,
.dialog-leave-active .dialog {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}
.dialog-enter-from .dialog,
.dialog-leave-to .dialog {
  transform: translateY(8px) scale(0.98);
  opacity: 0;
}
</style>
