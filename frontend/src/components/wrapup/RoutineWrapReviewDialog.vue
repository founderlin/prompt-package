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
          class="dialog dialog--wide"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
        >
          <header class="dialog__header">
            <div class="dialog__heading">
              <h2 :id="titleId" class="dialog__title">
                Routine Wrap · Review
              </h2>
              <p class="dialog__subtitle">
                Auto-generated weekly draft. Review and edit before
                saving — nothing is written until you click Save.
              </p>
            </div>
            <button
              class="dialog__close"
              type="button"
              :disabled="isBusy"
              aria-label="Close"
              @click="onCancel"
            >
              ×
            </button>
          </header>

          <div class="dialog__body">
            <p
              v-if="draft?.usedMock"
              class="banner banner--info"
              role="status"
            >
              <strong>Mock wrap.</strong>
              <span>
                No provider key on file — wrap was generated from a
                deterministic stub. Add a key in Settings for real
                LLM drafts.
              </span>
            </p>
            <p v-if="phase === 'failed'" class="banner banner--error" role="alert">
              <strong>{{ failedHeading }}</strong>
              <span>{{ errorMessage }}</span>
            </p>

            <section v-if="config" class="routine-meta-card">
              <dl class="routine-meta">
                <div class="routine-meta__row">
                  <dt>Cadence</dt>
                  <dd>{{ config.frequency }} · {{ config.dayOfWeek }}</dd>
                </div>
                <div class="routine-meta__row">
                  <dt>Model</dt>
                  <dd>
                    <code>{{ config.model }}</code>
                    <span v-if="effectiveModel && config.model === 'use-global-default'">
                      → <code>{{ effectiveModel }}</code>
                    </span>
                  </dd>
                </div>
                <div class="routine-meta__row">
                  <dt>Scope</dt>
                  <dd>{{ formatScope(config.scope) }}</dd>
                </div>
                <div class="routine-meta__row">
                  <dt>Last wrapped at</dt>
                  <dd>{{ formatTime(config.lastRunAt) || 'never' }}</dd>
                </div>
              </dl>
            </section>

            <section v-if="phase === 'analyzing' && !draft" class="rev-progress">
              <span class="spinner spinner--lg" aria-hidden="true" />
              <p>Generating routine draft…</p>
            </section>

            <template v-if="draft">
              <section class="rev-analysis">
                <h4 class="rev-section__title">Topic analysis</h4>
                <dl class="rev-analysis__rows">
                  <div class="rev-analysis__row">
                    <dt>Detected topic</dt>
                    <dd>{{ draft.analysis?.topic || '—' }}</dd>
                  </div>
                  <div class="rev-analysis__row">
                    <dt>Drift</dt>
                    <dd>
                      <span class="rev-pill" :class="driftPillClass">
                        {{ draft.analysis?.topicDrift ? 'detected' : 'none' }}
                      </span>
                    </dd>
                  </div>
                  <div class="rev-analysis__row">
                    <dt>Should split</dt>
                    <dd>
                      <span class="rev-pill" :class="splitPillClass">
                        {{ draft.analysis?.shouldSplit ? 'yes' : 'no' }}
                      </span>
                    </dd>
                  </div>
                </dl>
              </section>

              <section class="rev-editor">
                <header class="rev-editor__header">
                  <h4 class="rev-section__title">Markdown</h4>
                  <div class="rev-editor__meta">
                    <span class="rev-meta">
                      <code>{{ draft.suggestedFilename }}</code>
                    </span>
                    <span
                      v-if="isDirty"
                      class="rev-meta rev-meta--dirty"
                      title="You've edited the draft."
                    >
                      • edited
                    </span>
                  </div>
                </header>
                <textarea
                  v-model="editedMarkdown"
                  class="rev-editor__textarea"
                  spellcheck="false"
                  :disabled="phase === 'saving'"
                />
                <p class="rev-editor__hint">
                  {{ editedMarkdown.length }} characters · this exact
                  content will be written to disk on save.
                </p>
              </section>
            </template>
          </div>

          <footer class="dialog__actions">
            <button
              type="button"
              class="btn btn--ghost"
              :disabled="isBusy"
              @click="onCancel"
            >
              Cancel
            </button>
            <button
              type="button"
              class="btn btn--ghost"
              :disabled="phase !== 'failed' && phase !== 'ready'"
              title="Re-run the draft."
              @click="runDraft"
            >
              Re-draft
            </button>
            <button
              type="button"
              class="btn btn--primary"
              :disabled="!canSave"
              @click="onSave"
            >
              <span
                v-if="phase === 'saving'"
                class="spinner"
                aria-hidden="true"
              />
              <span>{{ phase === 'saving' ? 'Saving…' : 'Save wrap' }}</span>
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * RoutineWrapReviewDialog
 *
 * Phase 5 routine review window. Unlike Advanced Wrap, the model +
 * filters + scope come from the persisted routine config, so this
 * dialog is intentionally read-only on those knobs — the only
 * editable surface is the Markdown body. The user clicks Save to
 * persist; the parent invokes :func:`wrapsApi.markRoutineRun` after
 * a successful save to update ``last_run_at``.
 *
 * State machine:
 *
 *   idle  →  analyzing  →  ready  →  saving  →  closed
 *               ↘                       ↘
 *                failed ←──── retry ────┘
 *
 * Props:
 *   open           : boolean        — v-model:open
 *   projectId      : number|string  — required
 *   conversationId : number|string  — required
 *
 * Events:
 *   update:open    — for v-model:open
 *   close          — user dismissed the dialog
 *   saved(wrap)    — wrap persisted; payload is the SavedWrap object
 */
import { computed, nextTick, ref, watch } from 'vue'
import wrapsApi from '@/api/wraps'
import { describeApiError } from '@/utils/errors'

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: [Number, String], default: null },
  conversationId: { type: [Number, String], default: null }
})
const emit = defineEmits(['update:open', 'close', 'saved'])

const titleId = `routine-review-${Math.random().toString(36).slice(2, 8)}`

// 'idle' | 'analyzing' | 'ready' | 'saving' | 'failed'
const phase = ref('idle')
const draft = ref(null)
const config = ref(null)
const editedMarkdown = ref('')
const errorMessage = ref('')
const errorFrom = ref('') // 'analyzing' | 'saving'

const isBusy = computed(
  () => phase.value === 'analyzing' || phase.value === 'saving'
)
const isDirty = computed(
  () => draft.value !== null && editedMarkdown.value !== draft.value.markdown
)
const canSave = computed(
  () =>
    Boolean(draft.value) &&
    phase.value !== 'saving' &&
    editedMarkdown.value.trim().length > 0
)
const failedHeading = computed(() =>
  errorFrom.value === 'saving'
    ? 'Could not save the wrap.'
    : 'Could not generate the routine wrap.'
)
const driftPillClass = computed(() => ({
  'rev-pill--warn': draft.value?.analysis?.topicDrift,
  'rev-pill--ok': draft.value?.analysis?.topicDrift === false
}))
const splitPillClass = computed(() => ({
  'rev-pill--warn': draft.value?.analysis?.shouldSplit,
  'rev-pill--ok':
    draft.value && draft.value.analysis?.shouldSplit === false
}))

// The draft API echoes the *resolved* WrapModel back, so we surface
// it alongside the routine config to make "use-global-default → X"
// transparent. Renders ``null`` when config.model is concrete.
const effectiveModel = computed(() => draft.value?.model || null)

watch(
  () => props.open,
  async (next) => {
    if (next) {
      phase.value = 'idle'
      draft.value = null
      config.value = null
      editedMarkdown.value = ''
      errorMessage.value = ''
      errorFrom.value = ''
      await nextTick()
      runDraft()
    }
  }
)

async function runDraft() {
  phase.value = 'analyzing'
  errorMessage.value = ''
  errorFrom.value = ''
  try {
    const data = await wrapsApi.draftRoutine(
      props.projectId,
      props.conversationId
    )
    const newDraft = data?.draft || null
    config.value = data?.routineConfig || null
    if (!newDraft) {
      throw new Error('Server returned no routine draft.')
    }
    draft.value = newDraft
    editedMarkdown.value = newDraft.markdown || ''
    phase.value = 'ready'
  } catch (err) {
    errorMessage.value = describeApiError(
      err,
      'Could not generate the routine wrap draft.'
    )
    errorFrom.value = 'analyzing'
    phase.value = 'failed'
  }
}

async function onSave() {
  if (!draft.value || !editedMarkdown.value.trim()) return
  phase.value = 'saving'
  errorMessage.value = ''
  try {
    const data = await wrapsApi.save(props.projectId, {
      markdown: editedMarkdown.value,
      filename: draft.value.suggestedFilename
    })
    // After a successful save, stamp the routine config so the
    // cadence resets. We swallow errors here — a failure to mark
    // the run is annoying but not catastrophic; the wrap file is
    // already on disk.
    try {
      await wrapsApi.markRoutineRun(props.projectId)
    } catch (_err) {
      // Intentionally silent: file is saved, banner will just
      // re-appear sooner than expected. Worst-case the user
      // dismisses it once and moves on.
    }
    emit('saved', data?.wrap || null)
    closeDialog()
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not save wrap.')
    errorFrom.value = 'saving'
    phase.value = 'failed'
  }
}

function onBackdrop() {
  if (isBusy.value) return
  if (
    isDirty.value &&
    !confirm('You have unsaved edits. Close without saving?')
  ) {
    return
  }
  closeDialog()
}

function onCancel() {
  if (isBusy.value) return
  if (
    isDirty.value &&
    !confirm('You have unsaved edits. Close without saving?')
  ) {
    return
  }
  closeDialog()
}

function closeDialog() {
  emit('update:open', false)
  emit('close')
}

function formatScope(scope) {
  if (scope === 'since-last-wrap') return 'since last wrap'
  if (scope === 'last-7-days') return 'last 7 days'
  return scope || '—'
}

function formatTime(iso) {
  if (!iso) return null
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  } catch (_err) {
    return iso
  }
}
</script>

<style scoped>
.dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
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

.dialog--wide {
  width: min(960px, 100%);
}

.dialog__header {
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.dialog__heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dialog__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 500;
}

.dialog__subtitle {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  max-width: 600px;
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
  gap: var(--space-3);
  overflow: auto;
}

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
}

/* Banner */

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

/* Meta card */

.routine-meta-card {
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.routine-meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.routine-meta__row {
  display: grid;
  grid-template-columns: 160px 1fr;
  align-items: baseline;
  font-size: var(--text-sm);
}

.routine-meta__row dt {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.routine-meta__row dd {
  margin: 0;
  color: var(--color-text-primary);
}

.routine-meta__row dd code {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
  font-size: var(--text-xs);
}

/* Progress + analysis + editor */

.rev-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-5);
  text-align: center;
  color: var(--color-text-muted);
}

.rev-section__title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.rev-analysis {
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.rev-analysis__rows {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rev-analysis__row {
  display: grid;
  grid-template-columns: 120px 1fr;
  font-size: var(--text-sm);
}

.rev-analysis__row dt {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.rev-analysis__row dd {
  margin: 0;
  color: var(--color-text-primary);
}

.rev-pill {
  display: inline-flex;
  align-items: center;
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

.rev-pill--warn {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.4);
  color: #92400e;
}

.rev-pill--ok {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.35);
  color: #047857;
}

.rev-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rev-editor__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rev-editor__meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.rev-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.rev-meta--dirty {
  color: #b45309;
  font-weight: 500;
}

.rev-meta code {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
}

.rev-editor__textarea {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: var(--text-xs);
  line-height: 1.55;
  padding: 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-primary);
  min-height: 320px;
  resize: vertical;
  white-space: pre-wrap;
  tab-size: 2;
}

.rev-editor__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* Transition */

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
