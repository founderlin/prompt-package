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
            <div class="dialog__heading">
              <h2 :id="titleId" class="dialog__title">
                Routine Wrap Settings
              </h2>
              <p class="dialog__subtitle">
                Get a periodic reminder to wrap this project into a
                Markdown memory file. Review is always required —
                nothing is saved silently.
              </p>
            </div>
            <button
              class="dialog__close"
              type="button"
              :disabled="loading || saving"
              aria-label="Close"
              @click="onCancel"
            >
              ×
            </button>
          </header>

          <div class="dialog__body">
            <p v-if="errorMessage" class="banner banner--error" role="alert">
              <strong>
                {{ errorFrom === 'saving'
                    ? 'Could not save settings.'
                    : 'Could not load settings.' }}
              </strong>
              <span>{{ errorMessage }}</span>
            </p>

            <div v-if="loading" class="dialog__loading">
              <span class="spinner spinner--lg" aria-hidden="true" />
              <p>Loading routine settings…</p>
            </div>

            <template v-else>
              <section class="routine-card">
                <label class="routine-toggle">
                  <input
                    v-model="form.enabled"
                    type="checkbox"
                    :disabled="saving"
                  />
                  <span class="routine-toggle__label">
                    Enable Routine Wrap
                  </span>
                </label>
                <p class="routine-card__hint">
                  When enabled, a banner appears on the project once
                  the cadence elapses and there's new activity to
                  wrap.
                </p>
              </section>

              <section
                class="routine-card"
                :class="{ 'routine-card--muted': !form.enabled }"
              >
                <h4 class="routine-card__title">Cadence</h4>
                <div class="routine-grid">
                  <div class="routine-field">
                    <label class="routine-field__label" :for="freqId">
                      Frequency
                    </label>
                    <select
                      :id="freqId"
                      v-model="form.frequency"
                      class="routine-select"
                      :disabled="!form.enabled || saving"
                    >
                      <option value="weekly">weekly</option>
                      <option value="biweekly">biweekly</option>
                      <option value="monthly">monthly</option>
                    </select>
                  </div>
                  <div class="routine-field">
                    <label class="routine-field__label" :for="dayId">
                      Day
                    </label>
                    <select
                      :id="dayId"
                      v-model="form.dayOfWeek"
                      class="routine-select"
                      :disabled="!form.enabled || saving"
                    >
                      <option
                        v-for="d in DAYS"
                        :key="d.value"
                        :value="d.value"
                      >
                        {{ d.label }}
                      </option>
                    </select>
                  </div>
                </div>
                <p v-if="form.enabled" class="routine-card__hint">
                  The reminder fires as soon as the interval elapses
                  — the day is a hint for future scheduling.
                </p>
              </section>

              <section
                class="routine-card"
                :class="{ 'routine-card--muted': !form.enabled }"
              >
                <h4 class="routine-card__title">Wrap model &amp; scope</h4>
                <div class="routine-grid">
                  <div class="routine-field">
                    <label class="routine-field__label" :for="modelId">
                      Model
                    </label>
                    <select
                      :id="modelId"
                      v-model="form.model"
                      class="routine-select"
                      :disabled="!form.enabled || saving"
                    >
                      <option value="use-global-default">
                        use-global-default
                      </option>
                      <option value="deepseek-v4-flash">deepseek-v4-flash</option>
                      <option value="gemini-3.1-flash">gemini-3.1-flash</option>
                      <option value="gpt-5.4-nano">gpt-5.4-nano</option>
                    </select>
                  </div>
                  <div class="routine-field">
                    <label class="routine-field__label" :for="scopeId">
                      Scope
                    </label>
                    <select
                      :id="scopeId"
                      v-model="form.scope"
                      class="routine-select"
                      :disabled="!form.enabled || saving"
                    >
                      <option value="since-last-wrap">since last wrap</option>
                      <option value="last-7-days">last 7 days</option>
                    </select>
                  </div>
                </div>
              </section>

              <section class="routine-card routine-card--invariant">
                <h4 class="routine-card__title">Safety</h4>
                <ul class="routine-invariants">
                  <li>
                    <strong>Review required:</strong>
                    <span class="routine-pill routine-pill--ok">always on</span>
                    — the draft can't be saved without your approval.
                  </li>
                  <li>
                    <strong>Auto save:</strong>
                    <span class="routine-pill routine-pill--off">off</span>
                    — Phase 5 never writes the file in the background.
                  </li>
                </ul>
              </section>

              <section v-if="config" class="routine-card routine-card--meta">
                <h4 class="routine-card__title">State</h4>
                <dl class="routine-meta">
                  <div class="routine-meta__row">
                    <dt>Last wrapped at</dt>
                    <dd>{{ formatTime(config.lastRunAt) || 'never' }}</dd>
                  </div>
                  <div class="routine-meta__row">
                    <dt>Last dismissed at</dt>
                    <dd>{{ formatTime(config.dismissedAt) || '—' }}</dd>
                  </div>
                </dl>
              </section>
            </template>
          </div>

          <footer class="dialog__actions">
            <button
              type="button"
              class="btn btn--ghost"
              :disabled="saving"
              @click="onCancel"
            >
              Cancel
            </button>
            <button
              type="button"
              class="btn btn--primary"
              :disabled="loading || saving"
              @click="onSave"
            >
              <span v-if="saving" class="spinner" aria-hidden="true" />
              <span>{{ saving ? 'Saving…' : 'Save settings' }}</span>
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * RoutineWrapSettingsDialog
 *
 * Per-project routine configuration. Mirrors the backend
 * ``RoutineWrapConfig`` schema:
 *
 *   enabled       : boolean
 *   frequency     : 'weekly' | 'biweekly' | 'monthly'
 *   dayOfWeek     : 'monday' | … | 'sunday'
 *   model         : 'use-global-default' | <WrapModel value>
 *   scope         : 'since-last-wrap' | 'last-7-days'
 *
 * ``reviewRequired`` and ``autoSave`` are intentionally **not**
 * editable in Phase 5 — they are surfaced as read-only chips so
 * the user understands the safety contract.
 *
 * Props:
 *   open      : boolean        — v-model:open
 *   projectId : number|string  — required
 *
 * Events:
 *   update:open — for v-model:open
 *   close       — user dismissed the dialog
 *   saved       — settings persisted; payload is the updated config
 */
import { reactive, ref, watch } from 'vue'
import wrapsApi from '@/api/wraps'
import { describeApiError } from '@/utils/errors'

const DAYS = [
  { value: 'monday', label: 'Monday' },
  { value: 'tuesday', label: 'Tuesday' },
  { value: 'wednesday', label: 'Wednesday' },
  { value: 'thursday', label: 'Thursday' },
  { value: 'friday', label: 'Friday' },
  { value: 'saturday', label: 'Saturday' },
  { value: 'sunday', label: 'Sunday' }
]

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: [Number, String], default: null }
})
const emit = defineEmits(['update:open', 'close', 'saved'])

const _rand = Math.random().toString(36).slice(2, 8)
const titleId = `routine-title-${_rand}`
const freqId = `routine-freq-${_rand}`
const dayId = `routine-day-${_rand}`
const modelId = `routine-model-${_rand}`
const scopeId = `routine-scope-${_rand}`

const form = reactive({
  enabled: false,
  frequency: 'weekly',
  dayOfWeek: 'friday',
  model: 'use-global-default',
  scope: 'since-last-wrap'
})

// Loaded snapshot (so we can show lastRunAt/dismissedAt as read-only state).
const config = ref(null)
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const errorFrom = ref('') // 'loading' | 'saving'

watch(
  () => props.open,
  async (next) => {
    if (next) {
      errorMessage.value = ''
      errorFrom.value = ''
      await loadConfig()
    }
  }
)

async function loadConfig() {
  loading.value = true
  try {
    const data = await wrapsApi.getRoutineConfig(props.projectId)
    const cfg = data?.config || null
    config.value = cfg
    if (cfg) {
      form.enabled = Boolean(cfg.enabled)
      form.frequency = cfg.frequency || 'weekly'
      form.dayOfWeek = cfg.dayOfWeek || 'friday'
      form.model = cfg.model || 'use-global-default'
      form.scope = cfg.scope || 'since-last-wrap'
    }
  } catch (err) {
    errorMessage.value = describeApiError(
      err,
      'Could not load routine settings.'
    )
    errorFrom.value = 'loading'
  } finally {
    loading.value = false
  }
}

async function onSave() {
  if (saving.value) return
  saving.value = true
  errorMessage.value = ''
  errorFrom.value = ''
  try {
    const data = await wrapsApi.updateRoutineConfig(props.projectId, {
      enabled: form.enabled,
      frequency: form.frequency,
      dayOfWeek: form.dayOfWeek,
      model: form.model,
      scope: form.scope
    })
    const cfg = data?.config || null
    config.value = cfg
    emit('saved', cfg)
    closeDialog()
  } catch (err) {
    errorMessage.value = describeApiError(
      err,
      'Could not save routine settings.'
    )
    errorFrom.value = 'saving'
  } finally {
    saving.value = false
  }
}

function onBackdrop() {
  if (saving.value) return
  closeDialog()
}

function onCancel() {
  if (saving.value) return
  closeDialog()
}

function closeDialog() {
  emit('update:open', false)
  emit('close')
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
  max-width: 480px;
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

.dialog__loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-5);
  color: var(--color-text-muted);
}

.dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--color-border);
}

/* Cards */

.routine-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.routine-card--muted {
  opacity: 0.6;
}

.routine-card--invariant {
  background: var(--color-surface);
}

.routine-card__title {
  margin: 0;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  font-weight: 600;
}

.routine-card__hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.routine-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.routine-toggle__label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-primary);
}

.routine-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

@media (max-width: 560px) {
  .routine-grid {
    grid-template-columns: 1fr;
  }
}

.routine-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.routine-field__label {
  font-size: var(--text-xs);
  color: var(--color-text-primary);
  font-weight: 500;
}

.routine-select {
  font: inherit;
  font-size: var(--text-sm);
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-primary);
}

.routine-invariants {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.routine-pill {
  display: inline-flex;
  align-items: center;
  font-size: var(--text-xs);
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  margin: 0 4px;
}

.routine-pill--ok {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.35);
  color: #047857;
}

.routine-pill--off {
  background: rgba(244, 63, 94, 0.08);
  border-color: rgba(244, 63, 94, 0.35);
  color: #9f1239;
}

.routine-card--meta {
  background: var(--color-surface);
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

.banner--error {
  background: rgba(198, 40, 40, 0.06);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
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
