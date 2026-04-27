<template>
  <article class="model-card">
    <header class="model-card__header">
      <div>
        <h4 class="model-card__title">{{ provider.label }}</h4>
        <p class="model-card__lede text-secondary">
          {{ selected.length }}
          {{ selected.length === 1 ? 'model' : 'models' }} enabled
          <template v-if="selected.length === 0">
            · pick at least one to see it in the chat picker
          </template>
        </p>
      </div>
      <span class="chip chip--success">
        <span class="chip__dot" aria-hidden="true" />
        Connected
      </span>
    </header>

    <!-- Curated presets as toggleable chips -->
    <div v-if="presets.length" class="model-card__presets">
      <p class="model-card__section-label">Suggested</p>
      <ul class="model-card__chips">
        <li v-for="opt in presets" :key="opt.id">
          <button
            type="button"
            class="model-chip"
            :class="{ 'model-chip--on': isSelected(opt.id) }"
            :disabled="busy"
            :title="opt.hint || opt.id"
            @click="togglePreset(opt)"
          >
            <span class="model-chip__check" aria-hidden="true">
              {{ isSelected(opt.id) ? '✓' : '+' }}
            </span>
            <span class="model-chip__label">{{ opt.label }}</span>
            <span class="model-chip__vendor">{{ opt.vendor }}</span>
          </button>
        </li>
      </ul>
    </div>

    <!-- Custom-added (not in presets) -->
    <div v-if="customs.length" class="model-card__customs">
      <p class="model-card__section-label">Custom</p>
      <ul class="model-card__custom-list">
        <li v-for="row in customs" :key="row.model_id" class="model-card__custom-row">
          <code class="model-card__mono">{{ row.model_id }}</code>
          <span v-if="row.label" class="model-card__custom-label">
            {{ row.label }}
          </span>
          <button
            type="button"
            class="icon-btn icon-btn--danger"
            :disabled="busy"
            :aria-label="`Remove ${row.model_id}`"
            title="Remove"
            @click="removeOne(row.model_id)"
          >
            ×
          </button>
        </li>
      </ul>
    </div>

    <!-- Add custom model id -->
    <form class="model-card__add" @submit.prevent="addCustom">
      <label class="form-field">
        <span class="form-field__label">Add a custom model id</span>
        <div class="model-card__add-row">
          <input
            v-model="customModelId"
            class="model-card__input"
            :placeholder="placeholder"
            :disabled="busy"
            spellcheck="false"
            autocapitalize="off"
            autocomplete="off"
          />
          <input
            v-model="customLabel"
            class="model-card__input model-card__input--label"
            placeholder="Display label (optional)"
            :disabled="busy"
            spellcheck="false"
          />
          <button
            type="submit"
            class="btn btn--primary btn--sm"
            :disabled="busy || !customModelId.trim()"
          >
            <span v-if="saving" class="spinner" aria-hidden="true" />
            Add
          </button>
        </div>
      </label>
    </form>

    <div v-if="error" class="banner banner--error" role="alert">
      <span>{{ error }}</span>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import modelSelectionsApi from '@/api/modelSelections'
import { describeApiError } from '@/utils/errors'
import { MODEL_OPTIONS, findModelOption } from '@/constants/models'

const props = defineProps({
  provider: { type: Object, required: true },
  /** Array of { id, provider, model_id, label } returned from the API. */
  selections: { type: Array, default: () => [] }
})

const emit = defineEmits(['change'])

const saving = ref(false)
const removingId = ref(null)
const error = ref('')
const customModelId = ref('')
const customLabel = ref('')

const busy = computed(() => saving.value || removingId.value !== null)

const presets = computed(() =>
  MODEL_OPTIONS.filter((m) => m.provider === props.provider.id)
)

const presetIds = computed(() => new Set(presets.value.map((m) => m.id)))

const selected = computed(() => props.selections || [])

const customs = computed(() =>
  selected.value.filter((row) => !presetIds.value.has(row.model_id))
)

const placeholder = computed(() => {
  switch (props.provider.id) {
    case 'openrouter':
      return 'vendor/model-id e.g. mistralai/mixtral-8x7b-instruct'
    case 'deepseek':
      return 'deepseek-coder'
    case 'openai':
      return 'gpt-5-preview'
    default:
      return 'model-id'
  }
})

function isSelected(modelId) {
  return selected.value.some((r) => r.model_id === modelId)
}

async function togglePreset(opt) {
  if (busy.value) return
  error.value = ''
  saving.value = true
  try {
    if (isSelected(opt.id)) {
      // Remove
      await modelSelectionsApi.remove(props.provider.id, opt.id)
      emit('change', {
        provider: props.provider.id,
        removed: opt.id
      })
    } else {
      const data = await modelSelectionsApi.add(props.provider.id, {
        modelId: opt.id,
        label: opt.label
      })
      emit('change', {
        provider: props.provider.id,
        added: data?.model
      })
    }
  } catch (err) {
    error.value = describeApiError(err, 'Could not update your selection.')
  } finally {
    saving.value = false
  }
}

async function addCustom() {
  const mid = customModelId.value.trim()
  if (!mid || busy.value) return
  error.value = ''
  saving.value = true
  try {
    // If it happens to match a curated preset, reuse that label.
    const known = findModelOption(mid, props.provider.id)
    const label = customLabel.value.trim() || known?.label || ''
    const data = await modelSelectionsApi.add(props.provider.id, {
      modelId: mid,
      label: label || null
    })
    emit('change', {
      provider: props.provider.id,
      added: data?.model
    })
    customModelId.value = ''
    customLabel.value = ''
  } catch (err) {
    error.value = describeApiError(err, 'Could not add this model.')
  } finally {
    saving.value = false
  }
}

async function removeOne(modelId) {
  if (busy.value) return
  error.value = ''
  removingId.value = modelId
  try {
    await modelSelectionsApi.remove(props.provider.id, modelId)
    emit('change', { provider: props.provider.id, removed: modelId })
  } catch (err) {
    error.value = describeApiError(err, 'Could not remove this model.')
  } finally {
    removingId.value = null
  }
}
</script>

<style scoped>
.model-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.model-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.model-card__title {
  margin: 0 0 4px;
  font-size: var(--text-base);
  font-weight: 600;
}

.model-card__lede {
  margin: 0;
  font-size: var(--text-sm);
}

.model-card__section-label {
  margin: 0 0 6px;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  font-weight: 600;
}

.model-card__chips {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  font-size: var(--text-xs);
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: background-color 0.12s ease, border-color 0.12s ease,
    color 0.12s ease;
  font: inherit;
  font-size: var(--text-xs);
}

.model-chip:hover:not(:disabled) {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
}

.model-chip--on {
  background: var(--color-primary-soft);
  border-color: rgba(26, 115, 232, 0.5);
  color: var(--color-primary);
  font-weight: 500;
}

.model-chip--on:hover:not(:disabled) {
  background: var(--color-primary-soft);
}

.model-chip:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.model-chip__check {
  font-weight: 700;
  font-size: 11px;
  min-width: 12px;
  text-align: center;
}

.model-chip__vendor {
  color: var(--color-text-muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.model-card__custom-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.model-card__custom-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 6px 10px;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.model-card__mono {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: var(--text-xs);
  color: var(--color-text-primary);
  flex: 0 1 auto;
  word-break: break-all;
}

.model-card__custom-label {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  flex: 1;
}

.icon-btn {
  background: transparent;
  border: 1px solid transparent;
  color: var(--color-text-muted);
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  font-weight: 600;
}

.icon-btn:hover:not(:disabled) {
  background: rgba(198, 40, 40, 0.08);
  color: #c62828;
}

.icon-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.model-card__add-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  flex-wrap: wrap;
}

.model-card__input {
  flex: 1;
  min-width: 180px;
  padding: 8px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: var(--text-sm);
}

.model-card__input--label {
  font-family: inherit;
  min-width: 140px;
  flex: 0 1 auto;
}

.model-card__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.form-field__label {
  display: block;
  margin-bottom: 4px;
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  font-weight: 600;
}

.banner {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  border: 1px solid var(--color-border);
}

.banner--error {
  background: rgba(198, 40, 40, 0.06);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 500;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  height: fit-content;
}

.chip__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-text-muted);
}

.chip--success {
  background: rgba(46, 125, 50, 0.1);
  border-color: rgba(46, 125, 50, 0.4);
  color: #1b5e20;
}

.chip--success .chip__dot {
  background: #2e7d32;
}
</style>
