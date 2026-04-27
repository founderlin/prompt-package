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
              {{ isEdit ? 'Edit project' : 'New project' }}
            </h2>
            <button
              class="dialog__close"
              type="button"
              :disabled="busy"
              aria-label="Close"
              @click="onCancel"
            >
              ×
            </button>
          </header>

          <form class="dialog__body" @submit.prevent="onSubmit">
            <label class="form-field">
              <span class="form-field__label">Project name</span>
              <input
                ref="nameInputEl"
                v-model="form.name"
                class="form-field__input"
                type="text"
                maxlength="120"
                placeholder="e.g. Memory MVP"
                :disabled="busy"
                required
              />
              <span class="form-field__hint">{{ form.name.length }} / 120</span>
            </label>

            <label class="form-field">
              <span class="form-field__label">Description (optional)</span>
              <textarea
                v-model="form.description"
                class="form-field__input form-field__input--textarea"
                rows="4"
                maxlength="2000"
                placeholder="What is this project about? Who is it for?"
                :disabled="busy"
              />
              <span class="form-field__hint">{{ form.description.length }} / 2000</span>
            </label>

            <div v-if="error" class="banner banner--error" role="alert">
              {{ error }}
            </div>

            <footer class="dialog__actions">
              <button
                type="button"
                class="btn btn--ghost"
                :disabled="busy"
                @click="onCancel"
              >
                Cancel
              </button>
              <button
                type="submit"
                class="btn btn--primary"
                :disabled="busy || !form.name.trim()"
              >
                <span v-if="busy" class="spinner" aria-hidden="true" />
                {{
                  busy
                    ? isEdit
                      ? 'Saving…'
                      : 'Creating…'
                    : isEdit
                      ? 'Save changes'
                      : 'Create project'
                }}
              </button>
            </footer>
          </form>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import projectsApi from '@/api/projects'
import { describeApiError } from '@/utils/errors'

const props = defineProps({
  open: { type: Boolean, default: false },
  project: { type: Object, default: null }
})

const emit = defineEmits(['close', 'created', 'updated'])

const isEdit = computed(() => !!props.project?.id)
const titleId = `project-dialog-title-${Math.random().toString(36).slice(2, 8)}`

const form = reactive({ name: '', description: '' })
const busy = ref(false)
const error = ref('')
const nameInputEl = ref(null)

function reset() {
  form.name = props.project?.name || ''
  form.description = props.project?.description || ''
  error.value = ''
  busy.value = false
}

watch(
  () => props.open,
  async (next) => {
    if (next) {
      reset()
      await nextTick()
      nameInputEl.value?.focus()
      window.addEventListener('keydown', onKeydown)
    } else {
      window.removeEventListener('keydown', onKeydown)
    }
  }
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

function onKeydown(e) {
  if (e.key === 'Escape' && !busy.value) {
    emit('close')
  }
}

function onBackdrop() {
  if (!busy.value) emit('close')
}

function onCancel() {
  if (!busy.value) emit('close')
}

async function onSubmit() {
  if (busy.value) return
  const trimmedName = form.name.trim()
  if (!trimmedName) return

  busy.value = true
  error.value = ''
  try {
    const payload = {
      name: trimmedName,
      description: form.description.trim()
    }
    if (isEdit.value) {
      const data = await projectsApi.update(props.project.id, payload)
      emit('updated', data.project)
    } else {
      const data = await projectsApi.create(payload)
      emit('created', data.project)
    }
  } catch (err) {
    error.value = describeApiError(err, 'Could not save the project.')
  } finally {
    busy.value = false
  }
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
  width: min(560px, 100%);
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

.dialog__body {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  overflow: auto;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
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
  min-height: 96px;
}

.form-field__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  align-self: flex-end;
}

.banner {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
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
