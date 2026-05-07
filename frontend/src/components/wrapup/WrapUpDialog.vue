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
              :disabled="runningOrFailed && phase === 'running'"
              aria-label="Close"
              @click="onCancel"
            >
              ×
            </button>
          </header>

          <!-- FORM -->
          <form
            v-if="phase === 'form'"
            class="dialog__body"
            @submit.prevent="onSubmit"
          >
            <p class="dialog__lede">
              {{ scopeLede }}
            </p>

            <label class="form-field">
              <span class="form-field__label">Context Pack title (optional)</span>
              <input
                ref="titleInputEl"
                v-model="form.title"
                class="form-field__input"
                type="text"
                maxlength="160"
                :placeholder="titlePlaceholder"
              />
              <span class="form-field__hint">{{ form.title.length }} / 160</span>
            </label>

            <label class="form-field">
              <span class="form-field__label">Wrap-up goal (optional)</span>
              <textarea
                v-model="form.goal"
                class="form-field__input form-field__input--textarea"
                rows="3"
                maxlength="1000"
                placeholder="e.g. 整理本次技术方案讨论 / Focus on backend decisions"
              />
              <span class="form-field__hint">
                Guides what to emphasize. Leave blank for a generic summary.
              </span>
            </label>

            <label class="form-field form-field--inline">
              <input
                v-model="form.includeRawReferences"
                type="checkbox"
              />
              <span>
                <strong>Keep raw message references</strong>
                <span class="form-field__hint">
                  Records each source message alongside the pack for traceability.
                </span>
              </span>
            </label>

            <footer class="dialog__actions">
              <button
                type="button"
                class="btn btn--ghost"
                @click="onCancel"
              >
                Cancel
              </button>
              <button
                type="submit"
                class="btn btn--primary"
              >
                Wrap Up
              </button>
            </footer>
          </form>

          <!-- RUNNING -->
          <div v-else-if="phase === 'running'" class="dialog__body dialog__body--progress">
            <div class="wrapup-progress">
              <div class="wrapup-progress__spinner">
                <span class="spinner spinner--lg" aria-hidden="true" />
              </div>
              <h3 class="wrapup-progress__current">{{ currentStageLabel }}</h3>
              <div
                class="wrapup-progress__bar"
                role="progressbar"
                :aria-valuenow="progressValue"
                aria-valuemin="0"
                aria-valuemax="100"
              >
                <div
                  class="wrapup-progress__bar-fill"
                  :style="{ width: progressValue + '%' }"
                />
              </div>
              <ol class="wrapup-progress__steps">
                <li
                  v-for="(step, idx) in stages"
                  :key="step.key"
                  class="wrapup-progress__step"
                  :class="{
                    'wrapup-progress__step--done': idx < currentStageIndex,
                    'wrapup-progress__step--active': idx === currentStageIndex
                  }"
                >
                  <span class="wrapup-progress__dot" aria-hidden="true" />
                  {{ step.label }}
                </li>
              </ol>
            </div>
          </div>

          <!-- SUCCESS -->
          <div v-else-if="phase === 'success'" class="dialog__body">
            <div class="wrapup-result">
              <div class="wrapup-result__header">
                <svg
                  class="wrapup-result__check"
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2.2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span>Context Pack created</span>
              </div>

              <h3 class="wrapup-result__title">
                {{ resultPack?.title || 'Context Pack' }}
              </h3>

              <p v-if="resultPack?.description" class="wrapup-result__description">
                {{ resultPack.description }}
              </p>

              <section v-if="resultPack?.summary" class="wrapup-result__section">
                <h4 class="wrapup-result__section-title">Summary</h4>
                <p class="wrapup-result__summary">{{ resultPack.summary }}</p>
              </section>

              <section
                v-if="resultPack?.keywords && resultPack.keywords.length"
                class="wrapup-result__section"
              >
                <h4 class="wrapup-result__section-title">Keywords</h4>
                <ul class="wrapup-result__keywords">
                  <li
                    v-for="k in resultPack.keywords"
                    :key="k"
                    class="wrapup-result__keyword"
                  >
                    {{ k }}
                  </li>
                </ul>
              </section>

              <p v-if="usedFallback" class="wrapup-result__note">
                Generated without an LLM summary — add a provider key in Settings
                to get a richer pack next time.
              </p>
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
                @click="onViewPack"
              >
                View Context Pack
              </button>
            </footer>
          </div>

          <!-- FAILED -->
          <div v-else-if="phase === 'failed'" class="dialog__body">
            <div class="banner banner--error" role="alert">
              <strong>Wrap-up failed.</strong>
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
 * WrapUpDialog
 *
 * A single self-contained modal that drives the whole wrap-up flow:
 *
 *   form  →  running  →  success | failed
 *
 * Modes:
 *   :scope="'conversation'"  + :conversation-id="<id>"
 *   :scope="'project'"       + :project-id="<id>"
 *
 * Emits:
 *   close                         — user dismissed the dialog
 *   success(contextPack, job)     — wrap-up completed; payload mirrors the API
 *   view-pack(contextPack)        — user clicked "View Context Pack"
 *
 * Progress state machine:
 *   The HTTP request is synchronous on the backend so we can't actually
 *   stream real stage transitions. Instead we drive a local animated
 *   stage ticker that moves through the canonical stages and stops at
 *   the final stage when the request resolves. This is the "伪异步"
 *   required by the product spec. The same component will keep working
 *   unchanged when the backend gains a true queue — just swap the
 *   ticker for real job polling.
 */
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import wrapUpApi, { WRAP_UP_STAGES, WRAP_UP_STAGE_LABELS } from '@/api/wrapUp'
import { describeApiError } from '@/utils/errors'

const props = defineProps({
  open: { type: Boolean, default: false },
  /** 'conversation' | 'project' */
  scope: {
    type: String,
    default: 'conversation',
    validator: (v) => v === 'conversation' || v === 'project'
  },
  conversationId: { type: [Number, String], default: null },
  projectId: { type: [Number, String], default: null },
  /** Pre-populate the title field. */
  defaultTitle: { type: String, default: '' },
  /** Optional project/conversation names used in placeholder copy. */
  contextLabel: { type: String, default: '' }
})

const emit = defineEmits(['close', 'success', 'view-pack'])

const titleId = `wrap-up-dialog-title-${Math.random().toString(36).slice(2, 8)}`

// 'form' | 'running' | 'success' | 'failed'
const phase = ref('form')
const form = reactive({
  title: '',
  goal: '',
  includeRawReferences: true
})

const currentStageKey = ref(WRAP_UP_STAGES[0])
const progressValue = ref(0)
const errorMessage = ref('')
const resultPack = ref(null)
const resultJob = ref(null)
const usedFallback = ref(false)

const titleInputEl = ref(null)
let stageTicker = null

const runningOrFailed = computed(
  () => phase.value === 'running' || phase.value === 'failed'
)

const stages = computed(() =>
  WRAP_UP_STAGES.map((key) => ({
    key,
    label: WRAP_UP_STAGE_LABELS[key] || key
  }))
)

const currentStageIndex = computed(() => {
  const idx = WRAP_UP_STAGES.indexOf(currentStageKey.value)
  return idx < 0 ? 0 : idx
})

const currentStageLabel = computed(
  () => WRAP_UP_STAGE_LABELS[currentStageKey.value] || currentStageKey.value
)

const headerTitle = computed(() => {
  if (phase.value === 'success') return 'Context Pack ready'
  if (phase.value === 'failed') return 'Wrap-up failed'
  if (phase.value === 'running') {
    return props.scope === 'project' ? 'Wrapping project up…' : 'Wrapping up…'
  }
  return props.scope === 'project' ? 'Wrap Up Project' : 'Wrap Up Conversation'
})

const scopeLede = computed(() => {
  if (props.scope === 'project') {
    return 'Collect every conversation in this project into a single Context Pack you can reuse in future chats.'
  }
  return 'Distill this conversation into a Context Pack you can drop into future chats as seed context.'
})

const titlePlaceholder = computed(() => {
  const label = props.contextLabel?.trim()
  if (props.scope === 'project') {
    return label ? `${label} · Wrap Up` : 'Defaults to "Project · Wrap Up (timestamp)"'
  }
  return label ? `${label} · Wrap Up` : 'Defaults to "Conversation · Wrap Up (timestamp)"'
})

function resetForm() {
  form.title = props.defaultTitle || ''
  form.goal = ''
  form.includeRawReferences = true
}

function resetState() {
  resetForm()
  phase.value = 'form'
  currentStageKey.value = WRAP_UP_STAGES[0]
  progressValue.value = 0
  errorMessage.value = ''
  resultPack.value = null
  resultJob.value = null
  usedFallback.value = false
  stopTicker()
}

watch(
  () => props.open,
  async (next) => {
    if (next) {
      resetState()
      await nextTick()
      titleInputEl.value?.focus()
      window.addEventListener('keydown', onKeydown)
    } else {
      stopTicker()
      window.removeEventListener('keydown', onKeydown)
    }
  }
)

onBeforeUnmount(() => {
  stopTicker()
  window.removeEventListener('keydown', onKeydown)
})

function onKeydown(e) {
  if (e.key !== 'Escape') return
  // Don't allow dismissing mid-run; users can cancel by waiting it out
  // or by the failure / success path.
  if (phase.value === 'running') return
  emit('close')
}

function onBackdrop() {
  if (phase.value === 'running') return
  emit('close')
}

function onCancel() {
  if (phase.value === 'running') return
  emit('close')
}

async function onSubmit() {
  if (phase.value !== 'form') return

  phase.value = 'running'
  currentStageKey.value = WRAP_UP_STAGES[0]
  progressValue.value = 5
  errorMessage.value = ''
  startTicker()

  const payload = {
    title: form.title.trim() || undefined,
    goal: form.goal.trim() || undefined,
    options: {
      includeRawReferences: !!form.includeRawReferences
    }
  }

  try {
    const data = await callApi(payload)
    // Finish animation: jump to the final stage.
    currentStageKey.value = 'completed'
    progressValue.value = 100
    stopTicker()

    resultPack.value = data?.context_pack || null
    resultJob.value = data?.job || null
    usedFallback.value = !resultPack.value?.model

    // Brief delay so the 100% state is visible before flipping to success.
    await wait(250)
    phase.value = 'success'
    emit('success', resultPack.value, resultJob.value)
  } catch (err) {
    stopTicker()
    errorMessage.value = describeApiError(err, 'Could not wrap this up.')
    phase.value = 'failed'
  }
}

async function callApi(payload) {
  if (props.scope === 'project') {
    if (!props.projectId) {
      throw new Error('Missing projectId for project wrap-up.')
    }
    return wrapUpApi.forProject(props.projectId, payload)
  }
  if (!props.conversationId) {
    throw new Error('Missing conversationId for conversation wrap-up.')
  }
  return wrapUpApi.forConversation(props.conversationId, payload)
}

function onRetry() {
  phase.value = 'form'
  errorMessage.value = ''
}

function onViewPack() {
  if (!resultPack.value) {
    emit('close')
    return
  }
  emit('view-pack', resultPack.value)
}

// ---- Progress ticker ------------------------------------------------
//
// Walks through the canonical stages at a soft cadence so users see
// motion even though the real execution is synchronous. Intentionally
// stops one stage before the final 'completed' step — that transition
// is owned by the request resolver so the UI never lies about being
// finished before the server actually responds.

function startTicker() {
  stopTicker()
  let idx = 0
  const nonTerminal = WRAP_UP_STAGES.slice(0, -1) // drop 'completed'
  const maxProgressBeforeResolve = 88
  stageTicker = window.setInterval(() => {
    if (idx < nonTerminal.length - 1) {
      idx += 1
      currentStageKey.value = nonTerminal[idx]
    }
    // Soft exponential-ish approach to 88% so the bar keeps moving
    // without ever "arriving" while the request is still pending.
    progressValue.value = Math.min(
      maxProgressBeforeResolve,
      Math.round(progressValue.value + (maxProgressBeforeResolve - progressValue.value) * 0.18) + 1
    )
  }, 900)
}

function stopTicker() {
  if (stageTicker != null) {
    clearInterval(stageTicker)
    stageTicker = null
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
</script>

<style scoped>
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
  width: min(600px, 100%);
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
  min-height: 260px;
  align-items: center;
  justify-content: center;
}

.dialog__lede {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field--inline {
  flex-direction: row;
  align-items: flex-start;
  gap: var(--space-2);
}

.form-field--inline input[type='checkbox'] {
  margin-top: 4px;
}

.form-field__label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
}

.form-field__input {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
  background: var(--color-surface);
  font-size: var(--text-base);
  color: var(--color-text-primary);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  font-family: inherit;
}

.form-field__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.form-field__input--textarea {
  resize: vertical;
  min-height: 80px;
}

.form-field__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
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

.banner--error {
  background: rgba(198, 40, 40, 0.06);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

/* ---- Progress ------------------------------------------------------ */

.wrapup-progress {
  width: 100%;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  text-align: center;
}

.wrapup-progress__spinner .spinner--lg {
  width: 28px;
  height: 28px;
  border-width: 3px;
}

.wrapup-progress__current {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 500;
}

.wrapup-progress__bar {
  width: 100%;
  height: 6px;
  background: var(--color-surface-muted);
  border-radius: 999px;
  overflow: hidden;
}

.wrapup-progress__bar-fill {
  height: 100%;
  background: var(--color-primary);
  transition: width 0.45s ease;
}

.wrapup-progress__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-self: flex-start;
  width: 100%;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.wrapup-progress__step {
  display: flex;
  align-items: center;
  gap: 10px;
}

.wrapup-progress__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border);
  flex-shrink: 0;
}

.wrapup-progress__step--active {
  color: var(--color-text-primary);
  font-weight: 500;
}

.wrapup-progress__step--active .wrapup-progress__dot {
  background: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.wrapup-progress__step--done {
  color: var(--color-text-primary);
}

.wrapup-progress__step--done .wrapup-progress__dot {
  background: var(--color-primary);
}

/* ---- Result -------------------------------------------------------- */

.wrapup-result {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.wrapup-result__header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #1f7a43;
  font-weight: 500;
  font-size: var(--text-sm);
}

.wrapup-result__check {
  color: #1f7a43;
  flex-shrink: 0;
}

.wrapup-result__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}

.wrapup-result__description {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.wrapup-result__section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wrapup-result__section-title {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.wrapup-result__summary {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
  padding: 10px 12px;
  background: var(--color-surface-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.wrapup-result__keywords {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.wrapup-result__keyword {
  font-size: var(--text-xs);
  padding: 3px 8px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-primary);
}

.wrapup-result__note {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-style: italic;
}

/* ---- Dialog transitions (match ProjectFormDialog) ------------------- */

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
