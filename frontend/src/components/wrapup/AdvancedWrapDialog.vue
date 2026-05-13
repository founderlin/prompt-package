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
              <h2 :id="titleId" class="dialog__title">Advanced Wrap</h2>
              <p class="dialog__subtitle">
                Pick a model, tune filters, then review the Markdown
                before saving to <code>project-memory/wraps/</code>.
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
                No provider key for this model — wrap was generated
                from a deterministic stub. Add a key in Settings to
                get LLM-generated drafts.
              </span>
            </p>

            <p v-if="phase === 'failed'" class="banner banner--error" role="alert">
              <strong>{{ failedHeading }}</strong>
              <span>{{ errorMessage }}</span>
            </p>

            <div class="adv-grid">
              <!-- A. Model + scope ------------------------------------ -->
              <section class="adv-card adv-card--scope">
                <h4 class="adv-card__title">Model &amp; scope</h4>
                <div class="adv-field">
                  <label class="adv-field__label" :for="modelId">Model</label>
                  <select
                    :id="modelId"
                    v-model="model"
                    class="adv-select"
                    :disabled="isBusy"
                  >
                    <option
                      v-for="m in MODEL_OPTIONS"
                      :key="m.value"
                      :value="m.value"
                    >
                      {{ m.label }}
                    </option>
                  </select>
                </div>
                <div class="adv-field">
                  <label class="adv-field__label" :for="scopeId">Scope</label>
                  <select
                    :id="scopeId"
                    v-model="scope"
                    class="adv-select"
                    disabled
                  >
                    <option value="conversation">Current conversation</option>
                  </select>
                  <p class="adv-field__hint">
                    Only this conversation is supported in Phase 4.
                  </p>
                </div>
                <div class="adv-field">
                  <label class="adv-field__label" :for="instructionId">
                    Notes for the model
                    <span class="adv-field__optional">(optional)</span>
                  </label>
                  <textarea
                    :id="instructionId"
                    v-model="userInstruction"
                    class="adv-textarea adv-textarea--short"
                    rows="2"
                    placeholder="e.g. Focus on auth trade-offs. Keep code snippets short."
                    :disabled="isBusy"
                  />
                </div>
              </section>

              <!-- C. Filter rules (visually paired with scope card) -- -->
              <section class="adv-card adv-card--filters">
                <h4 class="adv-card__title">Filter rules</h4>
                <p class="adv-card__hint">
                  Tell the model what to do with each kind of content
                  it encounters in the transcript.
                </p>
                <div class="adv-filters">
                  <div
                    v-for="row in FILTER_ROWS"
                    :key="row.key"
                    class="adv-filter-row"
                  >
                    <label
                      class="adv-filter-row__label"
                      :for="`${filterIdBase}-${row.key}`"
                    >
                      {{ row.label }}
                    </label>
                    <select
                      :id="`${filterIdBase}-${row.key}`"
                      v-model="filters[row.key]"
                      class="adv-select adv-select--compact"
                      :disabled="isBusy"
                    >
                      <option value="keep">keep</option>
                      <option value="summarize">summarize</option>
                      <option value="exclude">exclude</option>
                    </select>
                  </div>
                </div>
              </section>

              <!-- B. Topic analysis ---------------------------------- -->
              <section class="adv-card adv-card--analysis">
                <header class="adv-card__header">
                  <h4 class="adv-card__title">Topic analysis</h4>
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm"
                    :disabled="phase === 'analyzing' || phase === 'saving'"
                    @click="runAnalyze"
                  >
                    <span
                      v-if="phase === 'analyzing'"
                      class="spinner"
                      aria-hidden="true"
                    />
                    <span>
                      {{ draft ? 'Re-analyze' : 'Analyze' }}
                    </span>
                  </button>
                </header>

                <div v-if="!draft && phase !== 'analyzing'" class="adv-empty">
                  <p>
                    Configure model + filters above, then click
                    <strong>Analyze</strong> to generate a draft.
                  </p>
                </div>

                <div v-else-if="phase === 'analyzing' && !draft" class="adv-empty">
                  <span class="spinner spinner--lg" aria-hidden="true" />
                  <p>Generating draft with <code>{{ model }}</code>…</p>
                </div>

                <div v-else-if="draft" class="adv-analysis">
                  <dl class="adv-analysis__rows">
                    <div class="adv-analysis__row">
                      <dt>Detected topic</dt>
                      <dd>{{ draft.analysis?.topic || '—' }}</dd>
                    </div>
                    <div class="adv-analysis__row">
                      <dt>Topic drift</dt>
                      <dd>
                        <span
                          class="adv-pill"
                          :class="driftPillClass"
                        >
                          {{ driftLabel }}
                        </span>
                      </dd>
                    </div>
                    <div class="adv-analysis__row">
                      <dt>Drift reason</dt>
                      <dd>{{ driftReason }}</dd>
                    </div>
                    <div class="adv-analysis__row">
                      <dt>Should split</dt>
                      <dd>
                        <span
                          class="adv-pill"
                          :class="splitPillClass"
                        >
                          {{ draft.analysis?.shouldSplit ? 'yes' : 'no' }}
                        </span>
                      </dd>
                    </div>
                  </dl>
                  <div
                    v-if="splitSuggestions.length"
                    class="adv-analysis__splits"
                  >
                    <h5 class="adv-analysis__splits-title">
                      Split suggestions
                    </h5>
                    <ul>
                      <li
                        v-for="(s, i) in splitSuggestions"
                        :key="i"
                      >
                        <strong>{{ s.title || `Sub-wrap ${i + 1}` }}</strong>
                        <span v-if="s.summary"> — {{ s.summary }}</span>
                      </li>
                    </ul>
                    <p class="adv-analysis__splits-hint">
                      Suggestions only — Advanced Wrap does not split
                      files automatically in this milestone.
                    </p>
                  </div>
                </div>
              </section>

              <!-- D. Markdown editor --------------------------------- -->
              <section class="adv-card adv-card--editor">
                <header class="adv-card__header">
                  <h4 class="adv-card__title">Markdown</h4>
                  <div class="adv-card__meta">
                    <span
                      v-if="draft"
                      class="adv-meta"
                      :title="draft.savePathRelative"
                    >
                      <code>{{ draft.suggestedFilename }}</code>
                    </span>
                    <span
                      v-if="isDirty"
                      class="adv-meta adv-meta--dirty"
                      title="You've edited the draft. Saving will write your edits."
                    >
                      • edited
                    </span>
                  </div>
                </header>
                <textarea
                  v-model="editedMarkdown"
                  class="adv-editor"
                  spellcheck="false"
                  :placeholder="
                    draft
                      ? 'Markdown will appear here after Analyze.'
                      : 'Click Analyze to generate a draft.'
                  "
                  :disabled="!draft || phase === 'saving'"
                />
                <p v-if="draft" class="adv-card__hint">
                  {{ editedMarkdown.length }} characters · this exact
                  content will be written to disk on save.
                </p>
              </section>
            </div>
          </div>

          <footer class="dialog__actions dialog__actions--sticky">
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
              :disabled="!draft || !isDirty || phase === 'saving'"
              title="Discard your edits and restore the model's draft."
              @click="resetEdits"
            >
              Reset edits
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
              <span>{{ phase === 'saving' ? 'Saving…' : 'Save' }}</span>
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * AdvancedWrapDialog
 *
 * The Phase 4 review window. Differs from QuickWrapDialog in three ways:
 *
 *   1. Caller chooses **model** + per-bucket **filters** + optional
 *      free-text instruction *before* the LLM call.
 *   2. The dialog shows the topic-analysis side of the response
 *      (drift, split suggestions) alongside the Markdown.
 *   3. The user can **edit the Markdown** in place; save writes the
 *      edited string, not the model's original draft.
 *
 * State machine:
 *
 *   idle          (user hasn't analyzed yet)
 *   analyzing     (POST /wraps/advanced-draft in flight)
 *   ready         (draft loaded, editor active)
 *   saving        (POST /wraps in flight)
 *   failed        (banner + retry/close)
 *
 * Re-clicking Analyze from `ready` returns to `analyzing` and
 * replaces the draft (discarding edits — guarded by a confirm if
 * dirty). Errors keep the previous draft around so the user can
 * fall back to it instead of losing context.
 *
 * Props:
 *   open           : boolean        — controls visibility (v-model:open)
 *   projectId      : number|string  — required
 *   conversationId : number|string  — required
 *
 * Events:
 *   update:open    — for v-model:open
 *   close          — user dismissed the dialog
 *   saved(wrap)    — wrap persisted; payload is the SavedWrap object
 */
import { computed, nextTick, reactive, ref, watch } from 'vue'
import wrapsApi from '@/api/wraps'
import { describeApiError } from '@/utils/errors'
import { getDefaultWrapModel } from '@/utils/wrapModelPref'

// Static lookup tables -----------------------------------------------------

// Mirrors the backend ``WrapModel`` enum (wrap_memory/types.py).
// Keeping the labels human-friendly while the value stays wire-stable.
const MODEL_OPTIONS = [
  { value: 'deepseek-v4-flash', label: 'deepseek-v4-flash' },
  { value: 'gemini-3.1-flash', label: 'gemini-3.1-flash' },
  { value: 'gpt-5.4-nano', label: 'gpt-5.4-nano' }
]

// Mirrors backend DEFAULT_FILTERS exactly (wrap_memory/settings.py).
// Source of truth lives in Python — copied here so the dialog can
// show a sensible default without a roundtrip on open.
const DEFAULT_FILTERS = Object.freeze({
  codeBlocks: 'summarize',
  images: 'exclude',
  promptText: 'summarize',
  logs: 'summarize',
  offTopic: 'exclude'
})

const FILTER_ROWS = [
  { key: 'codeBlocks', label: 'Code blocks' },
  { key: 'images', label: 'Images' },
  { key: 'promptText', label: 'Prompt text' },
  { key: 'logs', label: 'Logs' },
  { key: 'offTopic', label: 'Off-topic banter' }
]

// Source of truth for the dialog's pre-selected model:
// Settings → Wrap model (localStorage). Falls back to deepseek-v4-flash
// when unset, matching backend DEFAULT_MODEL.
const DEFAULT_MODEL = getDefaultWrapModel()

// Props / events ----------------------------------------------------------

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: [Number, String], default: null },
  conversationId: { type: [Number, String], default: null }
})
const emit = defineEmits(['update:open', 'close', 'saved'])

// Unique-ish DOM ids so the dialog can be mounted more than once
// without label collisions (e.g. dev-tools hot reload).
const _rand = Math.random().toString(36).slice(2, 8)
const titleId = `adv-wrap-title-${_rand}`
const modelId = `adv-wrap-model-${_rand}`
const scopeId = `adv-wrap-scope-${_rand}`
const instructionId = `adv-wrap-instruction-${_rand}`
const filterIdBase = `adv-wrap-filter-${_rand}`

// Form state --------------------------------------------------------------

const model = ref(DEFAULT_MODEL)
const scope = ref('conversation') // disabled select; here for future-proofing
const userInstruction = ref('')
const filters = reactive({ ...DEFAULT_FILTERS })

// Lifecycle / fetch state -------------------------------------------------

// 'idle' | 'analyzing' | 'ready' | 'saving' | 'failed'
const phase = ref('idle')
const draft = ref(null)
const editedMarkdown = ref('')
const errorMessage = ref('')
// 'analyzing' | 'saving' — set alongside phase=='failed' so the
// banner + retry copy can describe which operation actually failed.
const errorFrom = ref('')

const isBusy = computed(
  () => phase.value === 'analyzing' || phase.value === 'saving'
)

const isDirty = computed(() => {
  if (!draft.value) return false
  return editedMarkdown.value !== draft.value.markdown
})

const canSave = computed(() => {
  if (!draft.value) return false
  if (phase.value === 'saving') return false
  if (!editedMarkdown.value.trim()) return false
  return true
})

const failedHeading = computed(() => {
  if (errorFrom.value === 'saving') return 'Could not save the wrap.'
  return 'Could not generate the wrap.'
})

const splitSuggestions = computed(
  () => draft.value?.analysis?.splitSuggestions || []
)

// Drift is currently a boolean in the analysis payload, but we render
// it as a 3-level label (low/medium/high) so the UI is ready when the
// backend grows a finer-grained signal. Today: ``true → medium``.
const driftLabel = computed(() => {
  const drift = draft.value?.analysis?.topicDrift
  if (drift === true) return 'detected'
  if (drift === false) return 'none'
  return '—'
})

const driftPillClass = computed(() => ({
  'adv-pill--warn': driftLabel.value === 'detected',
  'adv-pill--ok': driftLabel.value === 'none'
}))

const splitPillClass = computed(() => ({
  'adv-pill--warn': draft.value?.analysis?.shouldSplit,
  'adv-pill--ok':
    draft.value && draft.value.analysis?.shouldSplit === false
}))

// The mock provider doesn't surface a structured drift reason, so we
// derive a short human-readable string from the available signals.
// Real LLM output may include a ``reason`` field later; until then,
// stating "drift detected — review suggestions" beats blanking the row.
const driftReason = computed(() => {
  if (!draft.value) return '—'
  const a = draft.value.analysis || {}
  if (a.topicDrift && a.shouldSplit) {
    return 'Drift detected and the model recommends splitting.'
  }
  if (a.topicDrift) {
    return 'Drift detected. Review the Markdown to confirm scope.'
  }
  if (a.shouldSplit) {
    return 'No drift, but the model still suggests sub-wraps.'
  }
  return 'Conversation stays on a single topic.'
})

// Open/close lifecycle ----------------------------------------------------

watch(
  () => props.open,
  async (next) => {
    if (next) {
      // Reset to defaults on every fresh open. We deliberately do
      // *not* auto-run analyze — Advanced Wrap is opt-in by design.
      phase.value = 'idle'
      draft.value = null
      editedMarkdown.value = ''
      errorMessage.value = ''
      errorFrom.value = ''
      // Re-read the preference each time — the user may have changed
      // their global default in Settings since the dialog last opened.
      model.value = getDefaultWrapModel()
      scope.value = 'conversation'
      userInstruction.value = ''
      Object.assign(filters, DEFAULT_FILTERS)
      await nextTick()
    }
  },
  { immediate: false }
)

// Actions -----------------------------------------------------------------

async function runAnalyze() {
  // Guard against losing in-progress edits.
  if (
    draft.value &&
    isDirty.value &&
    !confirm('Re-analyzing will discard your Markdown edits. Continue?')
  ) {
    return
  }
  phase.value = 'analyzing'
  errorMessage.value = ''
  errorFrom.value = ''
  try {
    const data = await wrapsApi.draftAdvanced(
      props.projectId,
      props.conversationId,
      {
        model: model.value,
        filters: { ...filters },
        userInstruction: userInstruction.value.trim() || undefined
      }
    )
    const newDraft = data?.draft || null
    if (!newDraft) {
      throw new Error('Server returned no draft payload.')
    }
    draft.value = newDraft
    editedMarkdown.value = newDraft.markdown || ''
    phase.value = 'ready'
  } catch (err) {
    errorMessage.value = describeApiError(
      err,
      'Could not generate wrap draft.'
    )
    errorFrom.value = 'analyzing'
    phase.value = 'failed'
  }
}

async function onSave() {
  if (!draft.value) return
  if (!editedMarkdown.value.trim()) return
  phase.value = 'saving'
  errorMessage.value = ''
  try {
    const data = await wrapsApi.save(props.projectId, {
      markdown: editedMarkdown.value,
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

function resetEdits() {
  if (!draft.value) return
  editedMarkdown.value = draft.value.markdown || ''
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
</script>

<style scoped>
/* Layout primitives mirror QuickWrapDialog so the two dialogs look
   like siblings. We deliberately keep the rules scoped (not shared)
   to avoid coupling future style tweaks. */

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
  width: min(1080px, 100%);
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

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.dialog__actions--sticky {
  position: sticky;
  bottom: 0;
  background: var(--color-surface);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
  margin-top: 0;
}

/* Banner ----------------------------------------------------------- */

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

/* 2-col grid that collapses to a stack on narrow screens. -------- */

.adv-grid {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(0, 1.5fr);
  grid-template-areas:
    'scope analysis'
    'filters analysis'
    'editor editor';
  gap: var(--space-3);
}

@media (max-width: 880px) {
  .adv-grid {
    grid-template-columns: 1fr;
    grid-template-areas:
      'scope'
      'filters'
      'analysis'
      'editor';
  }
}

.adv-card--scope {
  grid-area: scope;
}
.adv-card--filters {
  grid-area: filters;
}
.adv-card--analysis {
  grid-area: analysis;
}
.adv-card--editor {
  grid-area: editor;
}

.adv-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.adv-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.adv-card__title {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.adv-card__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.adv-card__meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.adv-meta {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.adv-meta--dirty {
  color: #b45309;
  font-weight: 500;
}

.adv-meta code {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
}

/* Form fields ------------------------------------------------------ */

.adv-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.adv-field__label {
  font-size: var(--text-xs);
  color: var(--color-text-primary);
  font-weight: 500;
}

.adv-field__optional {
  font-weight: 400;
  color: var(--color-text-muted);
}

.adv-field__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.adv-select {
  font: inherit;
  font-size: var(--text-sm);
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-primary);
}

.adv-select--compact {
  font-size: var(--text-xs);
  padding: 4px 6px;
  width: 110px;
}

.adv-textarea {
  font: inherit;
  font-size: var(--text-sm);
  padding: 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-primary);
  resize: vertical;
}

.adv-textarea--short {
  min-height: 56px;
}

/* Filter rules grid ----------------------------------------------- */

.adv-filters {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.adv-filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.adv-filter-row__label {
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

/* Analysis card -------------------------------------------------- */

.adv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-4);
  text-align: center;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.adv-empty p {
  margin: 0;
}

.adv-analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.adv-analysis__rows {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
}

.adv-analysis__row {
  display: grid;
  grid-template-columns: 110px 1fr;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.adv-analysis__row dt {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.adv-analysis__row dd {
  margin: 0;
  color: var(--color-text-primary);
  word-break: break-word;
}

.adv-pill {
  display: inline-flex;
  align-items: center;
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

.adv-pill--warn {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.4);
  color: #92400e;
}

.adv-pill--ok {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.35);
  color: #047857;
}

.adv-analysis__splits {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.adv-analysis__splits-title {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.adv-analysis__splits ul {
  margin: 0;
  padding-left: 18px;
  font-size: var(--text-sm);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.adv-analysis__splits-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-style: italic;
}

/* Markdown editor ------------------------------------------------- */

.adv-editor {
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

.adv-editor:disabled {
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

/* Transition ------------------------------------------------------ */

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
