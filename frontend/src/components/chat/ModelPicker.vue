<template>
  <div class="model-picker" ref="rootRef">
    <button
      type="button"
      class="model-picker__trigger"
      :class="{ 'model-picker__trigger--open': open }"
      :disabled="disabled"
      :aria-haspopup="'listbox'"
      :aria-expanded="open"
      @click="toggle"
      :title="currentTitle"
    >
      <span class="model-picker__trigger-prov">
        {{ currentProviderLabel }}
      </span>
      <span class="model-picker__trigger-model">
        {{ currentModelLabel }}
      </span>
      <span class="model-picker__caret" aria-hidden="true">▴</span>
    </button>

    <transition name="model-picker-fade">
      <div
        v-if="open"
        class="model-picker__panel"
        role="listbox"
        :aria-activedescendant="activeOptionId"
      >
        <div class="model-picker__search-row">
          <input
            ref="searchRef"
            v-model="query"
            type="search"
            class="model-picker__search"
            :placeholder="
              flatOptions.length
                ? 'Search models…'
                : 'No models yet — add some in Settings'
            "
            @keydown="onSearchKeydown"
          />
        </div>

        <div v-if="!flatOptions.length" class="model-picker__empty">
          <p class="text-secondary">
            You haven't enabled any models yet.
            <router-link to="/settings" class="link-inline" @click="close">
              Configure in Settings
            </router-link>
          </p>
        </div>

        <ul v-else class="model-picker__list">
          <template v-for="grp in filteredGroups" :key="grp.provider">
            <li
              v-if="grp.options.length"
              class="model-picker__group-label"
              aria-hidden="true"
            >
              {{ grp.label }}
            </li>
            <li
              v-for="opt in grp.options"
              :key="`${grp.provider}::${opt.model_id}`"
              :id="`mp-opt-${grp.provider}-${opt.model_id}`"
              class="model-picker__option"
              :class="{
                'model-picker__option--active':
                  activeIndex === opt._flatIndex,
                'model-picker__option--selected':
                  isCurrent(grp.provider, opt.model_id)
              }"
              role="option"
              :aria-selected="isCurrent(grp.provider, opt.model_id)"
              @click="select(grp.provider, opt)"
              @mouseenter="activeIndex = opt._flatIndex"
            >
              <span class="model-picker__option-label">
                {{ opt.label || opt.model_id }}
              </span>
              <span class="model-picker__option-id">{{ opt.model_id }}</span>
              <span
                v-if="isCurrent(grp.provider, opt.model_id)"
                class="model-picker__option-check"
                aria-hidden="true"
              >
                ✓
              </span>
            </li>
          </template>
          <li
            v-if="!filteredGroups.some((g) => g.options.length)"
            class="model-picker__empty"
          >
            <p class="text-secondary">No models match “{{ query }}”.</p>
          </li>
        </ul>

        <div class="model-picker__footer">
          <router-link to="/settings" class="link-inline" @click="close">
            Manage models in Settings →
          </router-link>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { findModelOption, PROVIDERS, providerLabel } from '@/constants/models'

const props = defineProps({
  /** Array of rows: { provider, model_id, label } */
  models: { type: Array, default: () => [] },
  currentModel: { type: String, default: '' },
  currentProvider: { type: String, default: '' },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['select'])

const rootRef = ref(null)
const searchRef = ref(null)
const open = ref(false)
const query = ref('')
const activeIndex = ref(0)

const providerOrder = PROVIDERS.map((p) => p.id)

const groupedAll = computed(() => {
  const map = new Map(providerOrder.map((id) => [id, []]))
  for (const row of props.models || []) {
    if (!map.has(row.provider)) map.set(row.provider, [])
    map.get(row.provider).push(row)
  }
  return providerOrder
    .filter((id) => (map.get(id) || []).length > 0)
    .map((id) => ({
      provider: id,
      label: providerLabel(id),
      options: map.get(id)
    }))
})

const filteredGroups = computed(() => {
  const q = query.value.trim().toLowerCase()
  let flatIdx = 0
  return groupedAll.value.map((grp) => {
    const filtered = grp.options
      .filter((opt) => {
        if (!q) return true
        const label = (opt.label || '').toLowerCase()
        const mid = (opt.model_id || '').toLowerCase()
        return label.includes(q) || mid.includes(q)
      })
      .map((opt) => ({ ...opt, _flatIndex: flatIdx++ }))
    return {
      ...grp,
      options: filtered
    }
  })
})

const flatOptions = computed(() =>
  filteredGroups.value.flatMap((g) =>
    g.options.map((opt) => ({ provider: g.provider, ...opt }))
  )
)

const currentProviderLabel = computed(() =>
  providerLabel(props.currentProvider)
)

const currentModelLabel = computed(() => {
  const preset = findModelOption(props.currentModel, props.currentProvider)
  if (preset?.label) return preset.label
  // Look up in user list for label override.
  const inList = (props.models || []).find(
    (m) =>
      m.provider === props.currentProvider &&
      m.model_id === props.currentModel
  )
  if (inList?.label) return inList.label
  return props.currentModel || 'Pick a model'
})

const currentTitle = computed(() =>
  props.currentModel
    ? `${currentProviderLabel.value} · ${props.currentModel}`
    : 'Pick a model'
)

const activeOptionId = computed(() => {
  const opt = flatOptions.value[activeIndex.value]
  if (!opt) return undefined
  return `mp-opt-${opt.provider}-${opt.model_id}`
})

function isCurrent(provider, modelId) {
  return (
    provider === props.currentProvider && modelId === props.currentModel
  )
}

function toggle() {
  if (props.disabled) return
  open.value ? close() : doOpen()
}

function doOpen() {
  open.value = true
  query.value = ''
  // Position the active index on the currently selected option if possible.
  const selectedIdx = flatOptions.value.findIndex((o) =>
    isCurrent(o.provider, o.model_id)
  )
  activeIndex.value = selectedIdx >= 0 ? selectedIdx : 0
  nextTick(() => searchRef.value?.focus())
}

function close() {
  open.value = false
}

function select(provider, opt) {
  emit('select', { provider, modelId: opt.model_id })
  close()
}

function onSearchKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (!flatOptions.value.length) return
    activeIndex.value =
      (activeIndex.value + 1) % flatOptions.value.length
    scrollActiveIntoView()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (!flatOptions.value.length) return
    activeIndex.value =
      (activeIndex.value - 1 + flatOptions.value.length) %
      flatOptions.value.length
    scrollActiveIntoView()
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const opt = flatOptions.value[activeIndex.value]
    if (opt) select(opt.provider, opt)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

function scrollActiveIntoView() {
  nextTick(() => {
    const el = document.getElementById(activeOptionId.value)
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest' })
    }
  })
}

function onDocumentClick(event) {
  if (!open.value) return
  if (rootRef.value && !rootRef.value.contains(event.target)) {
    close()
  }
}

function onDocumentKeydown(event) {
  if (open.value && event.key === 'Escape') close()
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('mousedown', onDocumentClick)
    document.addEventListener('keydown', onDocumentKeydown)
  } else {
    document.removeEventListener('mousedown', onDocumentClick)
    document.removeEventListener('keydown', onDocumentKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<style scoped>
.model-picker {
  position: relative;
  display: inline-flex;
}

.model-picker__trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font: inherit;
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  cursor: pointer;
  max-width: 320px;
  min-width: 0;
  transition: background-color 0.12s ease, border-color 0.12s ease,
    color 0.12s ease;
}

.model-picker__trigger:hover:not(:disabled),
.model-picker__trigger--open {
  background: var(--color-surface-hover);
  border-color: var(--color-border-strong);
  color: var(--color-text-primary);
}

.model-picker__trigger:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.model-picker__trigger-prov {
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--color-surface-muted);
  white-space: nowrap;
}

.model-picker__trigger-model {
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.model-picker__caret {
  font-size: 10px;
  color: var(--color-text-muted);
  margin-left: auto;
}

.model-picker__trigger--open .model-picker__caret {
  transform: rotate(180deg);
}

/* Panel expands UPWARD (OpenCode style). */
.model-picker__panel {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  width: min(420px, 90vw);
  max-height: 360px;
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: 0 -6px 24px rgba(15, 23, 42, 0.14),
    0 2px 6px rgba(15, 23, 42, 0.08);
  overflow: hidden;
  z-index: 50;
}

.model-picker__search-row {
  padding: 8px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-muted);
}

.model-picker__search {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  font: inherit;
  font-size: var(--text-sm);
}

.model-picker__search:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.model-picker__list {
  list-style: none;
  margin: 0;
  padding: 4px;
  overflow-y: auto;
  flex: 1;
}

.model-picker__group-label {
  padding: 6px 10px 2px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
  font-weight: 600;
}

.model-picker__option {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    'label check'
    'id    check';
  align-items: center;
  gap: 0 10px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.model-picker__option:hover,
.model-picker__option--active {
  background: var(--color-surface-hover);
}

.model-picker__option--selected {
  background: var(--color-primary-soft);
}

.model-picker__option-label {
  grid-area: label;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.model-picker__option-id {
  grid-area: id;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 10px;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.model-picker__option-check {
  grid-area: check;
  color: var(--color-primary);
  font-weight: 700;
}

.model-picker__empty {
  padding: var(--space-3);
  text-align: center;
}

.model-picker__footer {
  padding: 6px 10px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  font-size: var(--text-xs);
  text-align: right;
}

.link-inline {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}

.link-inline:hover {
  text-decoration: underline;
}

.model-picker-fade-enter-active,
.model-picker-fade-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}

.model-picker-fade-enter-from,
.model-picker-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
