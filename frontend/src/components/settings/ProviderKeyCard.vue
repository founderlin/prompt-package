<template>
  <article class="provider-card" :class="{ 'provider-card--configured': status?.configured }">
    <header class="provider-card__header">
      <div class="provider-card__heading">
        <h4 class="provider-card__title">{{ provider.label }}</h4>
        <p class="provider-card__lede text-secondary">{{ provider.description }}</p>
        <a
          v-if="provider.docs_url"
          class="provider-card__docs"
          :href="provider.docs_url"
          target="_blank"
          rel="noopener"
        >
          Get a key →
        </a>
      </div>
      <span
        class="chip"
        :class="status?.configured ? 'chip--success' : 'chip--neutral'"
      >
        <span class="chip__dot" aria-hidden="true" />
        {{ status?.configured ? 'Connected' : 'Not configured' }}
      </span>
    </header>

    <div v-if="status?.configured" class="provider-card__current">
      <div class="provider-card__current-row">
        <span class="provider-card__current-label">On file</span>
        <code class="provider-card__masked">{{ status.masked || '••••••••' }}</code>
      </div>
      <div v-if="status.updated_at" class="provider-card__current-row">
        <span class="provider-card__current-label">Last updated</span>
        <span class="text-secondary">{{ formatDateTime(status.updated_at) || '—' }}</span>
      </div>
    </div>

    <form class="provider-card__form" @submit.prevent="onSave" autocomplete="off">
      <label class="form-field">
        <span class="form-field__label">
          {{ status?.configured ? 'Replace API key' : 'API key' }}
        </span>
        <div class="key-input">
          <input
            class="key-input__field"
            :type="showKey ? 'text' : 'password'"
            :placeholder="placeholderForProvider"
            v-model="apiKey"
            :disabled="busy"
            spellcheck="false"
            autocapitalize="off"
            autocomplete="off"
            inputmode="latin"
            data-1p-ignore
            data-lpignore="true"
          />
          <button
            type="button"
            class="key-input__toggle"
            @click="showKey = !showKey"
            :aria-pressed="showKey"
            :title="showKey ? 'Hide key' : 'Show key'"
          >
            {{ showKey ? 'Hide' : 'Show' }}
          </button>
        </div>
      </label>

      <div
        v-if="banner"
        class="banner"
        :class="`banner--${banner.kind}`"
        role="status"
      >
        <strong v-if="banner.title">{{ banner.title }}</strong>
        <span>{{ banner.message }}</span>
        <ul v-if="banner.details?.length" class="banner__details">
          <li v-for="(line, idx) in banner.details" :key="idx">{{ line }}</li>
        </ul>
      </div>

      <div class="provider-card__actions">
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="busy || (!apiKey && !status?.configured)"
          @click="onTest"
        >
          <span v-if="testing" class="spinner" aria-hidden="true" />
          {{ testing ? 'Testing…' : 'Test connection' }}
        </button>

        <button
          type="submit"
          class="btn btn--primary"
          :disabled="busy || !apiKey"
        >
          <span v-if="saving" class="spinner" aria-hidden="true" />
          {{ saving ? 'Saving…' : status?.configured ? 'Replace key' : 'Save key' }}
        </button>

        <button
          v-if="status?.configured"
          type="button"
          class="btn btn--danger btn--ghost"
          :disabled="busy"
          @click="onRemove"
        >
          <span v-if="removing" class="spinner" aria-hidden="true" />
          {{ removing ? 'Removing…' : 'Remove key' }}
        </button>
      </div>
    </form>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import providersApi from '@/api/providers'
import { describeApiError } from '@/utils/errors'
import { formatDateTime } from '@/utils/time'

const props = defineProps({
  provider: {
    type: Object,
    required: true
  },
  status: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['saved', 'removed'])

const apiKey = ref('')
const showKey = ref(false)
const saving = ref(false)
const testing = ref(false)
const removing = ref(false)
const banner = ref(null)

const busy = computed(() => saving.value || testing.value || removing.value)

const placeholderForProvider = computed(() => {
  if (props.status?.configured) return 'Paste a new key to replace the one above'
  switch (props.provider.id) {
    case 'openrouter':
      return 'sk-or-v1-…'
    case 'deepseek':
      return 'sk-…'
    case 'openai':
      return 'sk-proj-…'
    default:
      return 'sk-…'
  }
})

function setBanner(kind, message, { title = '', details = [] } = {}) {
  banner.value = { kind, message, title, details }
}

function clearBanner() {
  banner.value = null
}

function detailsFromKeyInfo(info) {
  if (!info) return []
  const out = []
  if (info.label) out.push(`Label: ${info.label}`)
  if (typeof info.usage === 'number') out.push(`Usage so far: $${info.usage.toFixed(4)}`)
  if (info.limit !== null && info.limit !== undefined)
    out.push(`Limit: $${Number(info.limit).toFixed(2)}`)
  if (info.limit_remaining !== null && info.limit_remaining !== undefined)
    out.push(`Remaining: $${Number(info.limit_remaining).toFixed(2)}`)
  if (info.is_free_tier) out.push('Free-tier key')
  if (typeof info.model_count === 'number')
    out.push(`Models reachable: ${info.model_count}`)
  return out
}

async function onTest() {
  if (busy.value) return
  clearBanner()
  testing.value = true
  try {
    const data = await providersApi.testKey(props.provider.id, {
      apiKey: apiKey.value || null
    })
    setBanner(
      'success',
      apiKey.value
        ? 'Looks good. This key is valid — save it to start using it.'
        : 'Looks good. Your stored key is still valid.',
      {
        title: `${props.provider.label} accepted the key`,
        details: detailsFromKeyInfo(data?.key_info)
      }
    )
  } catch (err) {
    setBanner('error', describeApiError(err, 'Could not verify this key.'), {
      title: 'Test failed'
    })
  } finally {
    testing.value = false
  }
}

async function onSave() {
  if (busy.value || !apiKey.value) return
  clearBanner()
  saving.value = true
  try {
    const data = await providersApi.saveKey(props.provider.id, {
      apiKey: apiKey.value
    })
    setBanner(
      'success',
      `Your ${props.provider.label} API key is saved and encrypted.`,
      { title: 'Saved', details: detailsFromKeyInfo(data?.key_info) }
    )
    apiKey.value = ''
    showKey.value = false
    emit('saved', { provider: props.provider.id, status: data?.provider })
  } catch (err) {
    setBanner('error', describeApiError(err, 'Could not save the API key.'), {
      title: 'Save failed'
    })
  } finally {
    saving.value = false
  }
}

async function onRemove() {
  if (busy.value) return
  if (!props.status?.configured) return
  const ok = window.confirm(
    `Remove your ${props.provider.label} API key? You will need to paste it again to chat using this provider.`
  )
  if (!ok) return
  clearBanner()
  removing.value = true
  try {
    const data = await providersApi.deleteKey(props.provider.id)
    setBanner('success', 'API key removed.')
    apiKey.value = ''
    showKey.value = false
    emit('removed', { provider: props.provider.id, status: data?.provider })
  } catch (err) {
    setBanner('error', describeApiError(err, 'Could not remove the API key.'), {
      title: 'Remove failed'
    })
  } finally {
    removing.value = false
  }
}
</script>

<style scoped>
.provider-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.provider-card--configured {
  border-color: rgba(46, 125, 50, 0.35);
  background: rgba(46, 125, 50, 0.03);
}

.provider-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.provider-card__heading {
  flex: 1;
  min-width: 0;
}

.provider-card__title {
  margin: 0 0 4px;
  font-size: var(--text-base);
  font-weight: 600;
}

.provider-card__lede {
  margin: 0 0 4px;
  font-size: var(--text-sm);
}

.provider-card__docs {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-primary);
  text-decoration: none;
}

.provider-card__docs:hover {
  text-decoration: underline;
}

.provider-card__current {
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.provider-card__current-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.provider-card__current-label {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
}

.provider-card__masked {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: var(--text-sm);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  letter-spacing: 0.5px;
}

.provider-card__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.key-input {
  position: relative;
  display: flex;
  align-items: center;
}

.key-input__field {
  flex: 1;
  width: 100%;
  padding: 10px 78px 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: var(--text-sm);
  color: var(--color-text);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.key-input__field:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft, rgba(26, 115, 232, 0.18));
}

.key-input__toggle {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-primary);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.key-input__toggle:hover {
  background: var(--color-primary-soft, rgba(26, 115, 232, 0.1));
}

.provider-card__actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.banner {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
}

.banner strong {
  font-weight: 600;
}

.banner__details {
  margin: 6px 0 0;
  padding-left: 1.1em;
  color: var(--color-text-secondary);
}

.banner--success {
  background: rgba(46, 125, 50, 0.06);
  border-color: rgba(46, 125, 50, 0.35);
  color: #1b5e20;
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

.chip--neutral .chip__dot {
  background: var(--color-text-muted);
}

@media (max-width: 560px) {
  .provider-card__actions .btn {
    flex: 1;
  }
}
</style>
