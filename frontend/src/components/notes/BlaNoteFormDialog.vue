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
              {{ mode === 'create' ? 'New Bla Note' : 'Edit Bla Note' }}
            </h2>
          </header>

          <form class="dialog__body" @submit.prevent="onSubmit">
            <div class="field">
              <label :for="titleFieldId" class="field__label">
                Title <span class="field__required">*</span>
              </label>
              <input
                :id="titleFieldId"
                ref="titleInput"
                v-model="localTitle"
                type="text"
                class="input"
                placeholder="e.g. Product ideas, Technical debt, Meeting notes"
                maxlength="200"
                :disabled="busy"
                required
              />
            </div>

            <div class="field">
              <label :for="contentFieldId" class="field__label">
                Content
              </label>
              <p class="field__hint">
                Markdown supported. Use this space to capture ideas, decisions,
                or any context you want to reference later.
              </p>
              <textarea
                :id="contentFieldId"
                v-model="localContent"
                class="textarea dialog__textarea"
                placeholder="# Your notes here…

You can use **Markdown** formatting.

- Bullet points
- [ ] Todo items
- Links, code blocks, etc."
                :disabled="busy"
              />
            </div>

            <div class="field">
              <label :for="tagsFieldId" class="field__label">
                Tags
              </label>
              <p class="field__hint">
                Comma-separated. e.g. "idea, todo, design"
              </p>
              <input
                :id="tagsFieldId"
                v-model="localTags"
                type="text"
                class="input"
                placeholder="idea, todo, design"
                :disabled="busy"
              />
              <div v-if="parsedTags.length" class="dialog__tag-preview">
                <span
                  v-for="(tag, idx) in parsedTags"
                  :key="idx"
                  class="chip chip--primary"
                >
                  {{ tag }}
                </span>
              </div>
            </div>

            <div v-if="errorMessage" class="banner banner--error" role="alert">
              {{ errorMessage }}
            </div>
          </form>

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
              type="button"
              class="btn btn--primary"
              :disabled="busy || !canSave"
              @click="onSubmit"
            >
              <span v-if="busy" class="spinner" aria-hidden="true" />
              {{ busy ? 'Saving…' : mode === 'create' ? 'Create' : 'Save' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
/**
 * BlaNoteFormDialog — create or edit a Bla Note.
 *
 * Props:
 *   open       — v-model-able boolean
 *   mode       — 'create' | 'edit'
 *   projectId  — required for create; ignored for edit
 *   note       — when mode='edit', the existing note to populate fields
 *
 * Emits:
 *   save       — { title, content, tags } (create) or { id, title, content, tags } (edit)
 *   cancel     — user dismissed
 *   update:open
 *
 * The parent is responsible for calling the API and handling success /
 * error toasts. This component only manages the form state and
 * validation.
 */
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  mode: {
    type: String,
    default: 'create',
    validator: (v) => v === 'create' || v === 'edit'
  },
  projectId: { type: [Number, String], default: null },
  note: { type: Object, default: null },
  busy: { type: Boolean, default: false }
})

const emit = defineEmits(['save', 'cancel', 'update:open'])

const uid = Math.random().toString(36).slice(2, 8)
const titleId = `bla-note-dialog-title-${uid}`
const titleFieldId = `bla-note-title-${uid}`
const contentFieldId = `bla-note-content-${uid}`
const tagsFieldId = `bla-note-tags-${uid}`

const titleInput = ref(null)
const localTitle = ref('')
const localContent = ref('')
const localTags = ref('')
const errorMessage = ref('')

watch(
  () => props.open,
  async (next) => {
    if (next) {
      // Hydrate from props.note if editing.
      if (props.mode === 'edit' && props.note) {
        localTitle.value = props.note.title || ''
        localContent.value = props.note.content || ''
        const tags = Array.isArray(props.note.tags) ? props.note.tags : []
        localTags.value = tags.join(', ')
      } else {
        localTitle.value = ''
        localContent.value = ''
        localTags.value = ''
      }
      errorMessage.value = ''
      await nextTick()
      titleInput.value?.focus()
      window.addEventListener('keydown', onKeydown)
    } else {
      window.removeEventListener('keydown', onKeydown)
    }
  }
)

const parsedTags = computed(() => {
  if (!localTags.value) return []
  return localTags.value
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
})

const canSave = computed(() => {
  return localTitle.value.trim().length > 0
})

function onKeydown(e) {
  if (e.key === 'Escape' && !props.busy) {
    emitCancel()
  }
}

function onBackdrop() {
  if (props.busy) return
  emitCancel()
}

function onCancel() {
  if (props.busy) return
  emitCancel()
}

function emitCancel() {
  emit('cancel')
  emit('update:open', false)
}

function onSubmit() {
  if (props.busy || !canSave.value) return
  errorMessage.value = ''

  const payload = {
    title: localTitle.value.trim(),
    content: localContent.value,
    tags: parsedTags.value
  }

  if (props.mode === 'edit' && props.note) {
    payload.id = props.note.id
  }

  emit('save', payload)
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
  width: min(640px, 100%);
  max-height: 90vh;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-3, 0 20px 50px rgba(0, 0, 0, 0.18));
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dialog__header {
  padding: var(--space-4) var(--space-5) 0;
  flex-shrink: 0;
}

.dialog__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 500;
  color: var(--color-text-primary);
}

.dialog__body {
  padding: var(--space-3) var(--space-5) var(--space-5);
  overflow-y: auto;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.dialog__textarea {
  min-height: 240px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.6;
}

.dialog__tag-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.dialog__actions {
  padding: var(--space-3) var(--space-5) var(--space-4);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  flex-shrink: 0;
}

.banner {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
}

.banner--error {
  background: var(--color-error-soft);
  border-color: rgba(198, 40, 40, 0.35);
  color: #b71c1c;
}

.field__required {
  color: var(--color-error);
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
