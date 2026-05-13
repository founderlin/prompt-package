<template>
  <div class="settings-view">
    <PageHeader
      title="Settings"
      description="Manage your account, API keys, chat models, and wrap defaults."
    />

    <section class="card">
      <h3 class="card__title card__title--sm">Account</h3>

      <div class="account-row">
        <div class="account-row__avatar" aria-hidden="true">{{ initial }}</div>
        <div class="account-row__text">
          <span class="account-row__label">Signed in as</span>
          <span class="account-row__email">{{ user?.email || '—' }}</span>
          <span v-if="user?.created_at" class="account-row__hint">
            Joined {{ formatDateTime(user.created_at) || '—' }}
          </span>
        </div>
        <button
          class="btn btn--danger"
          type="button"
          @click="onLogout"
          :disabled="loggingOut"
        >
          <span v-if="loggingOut" class="spinner" aria-hidden="true" />
          {{ loggingOut ? 'Signing out…' : 'Sign out' }}
        </button>
      </div>
    </section>

    <!-- ====================================================================
         1. API keys
         Provider credentials. Independent from the model-picker rows below
         so the user can swap keys without re-curating chat or wrap models.
         ==================================================================== -->
    <section class="card settings-section">
      <header class="settings-section__head">
        <h3 class="card__title card__title--sm">API keys</h3>
        <span class="settings-section__badge">Step 1</span>
      </header>
      <p class="text-secondary settings-section__hint">
        Bring your own keys. Add one or more provider credentials —
        Chat and Wrap models below depend on having at least one key.
      </p>

      <div v-if="loadingProviders" class="provider-cards__loading">
        <span class="spinner" aria-hidden="true" />
        <span class="text-secondary">Loading provider settings…</span>
      </div>

      <div v-else class="provider-cards">
        <ProviderKeyCard
          v-for="cfg in providers"
          :key="cfg.id"
          :provider="cfg"
          :status="statuses[cfg.id]"
          @saved="onProviderSaved"
          @removed="onProviderRemoved"
        />
      </div>
    </section>

    <!-- ====================================================================
         2. Chat models
         Curates the model picker that shows up in the chat composer.
         ==================================================================== -->
    <section class="card settings-section">
      <header class="settings-section__head">
        <h3 class="card__title card__title--sm">Chat models</h3>
        <span class="settings-section__badge">Step 2</span>
      </header>
      <p class="text-secondary settings-section__hint">
        Pick the models you want to see in the chat composer's model
        picker. Each provider is independent — you can enable several
        from OpenRouter, DeepSeek, and OpenAI at the same time.
      </p>

      <div v-if="loadingProviders || loadingModels" class="provider-cards__loading">
        <span class="spinner" aria-hidden="true" />
        <span class="text-secondary">Loading model settings…</span>
      </div>

      <div
        v-else-if="!configuredProviders.length"
        class="banner banner--empty"
      >
        <strong>No provider keys yet.</strong>
        <span>
          Add at least one API key above — then come back to curate which
          models show up in the chat picker.
        </span>
      </div>

      <div v-else class="provider-cards">
        <ProviderModelSelections
          v-for="cfg in configuredProviders"
          :key="cfg.id"
          :provider="cfg"
          :selections="modelsByProvider[cfg.id] || []"
          @change="onModelsChanged"
        />
      </div>
    </section>

    <!-- ====================================================================
         3. Wrap model
         A small fast/cheap catalog dedicated to wrap generation. The
         picker here is the *default* surfaced by Quick / Advanced wrap
         dialogs and by Routine Wrap's ``use-global-default``.
         ==================================================================== -->
    <section class="card settings-section">
      <header class="settings-section__head">
        <h3 class="card__title card__title--sm">Wrap model</h3>
        <span class="settings-section__badge">Step 3</span>
      </header>
      <p class="text-secondary settings-section__hint">
        The default model used when you wrap a conversation into a
        Markdown memory file. You can still override it per-wrap from
        the Advanced dialog.
      </p>

      <div class="wrap-model-list" role="radiogroup" aria-label="Default wrap model">
        <label
          v-for="opt in WRAP_MODELS"
          :key="opt.id"
          class="wrap-model-option"
          :class="{ 'wrap-model-option--active': defaultWrapModel === opt.id }"
        >
          <input
            type="radio"
            name="default-wrap-model"
            :value="opt.id"
            :checked="defaultWrapModel === opt.id"
            @change="onWrapModelChange(opt.id)"
          />
          <div class="wrap-model-option__text">
            <span class="wrap-model-option__label">{{ opt.label }}</span>
            <span class="wrap-model-option__hint">{{ opt.hint }}</span>
          </div>
          <code class="wrap-model-option__id">{{ opt.id }}</code>
        </label>
      </div>

      <p
        v-if="wrapModelSaved"
        class="settings-section__feedback"
        role="status"
      >
        Default wrap model updated.
      </p>
    </section>

    <section class="card">
      <h3 class="card__title card__title--sm">Danger zone</h3>
      <p class="text-secondary" style="margin: 0 0 var(--space-3)">
        Full data deletion controls will live here.
      </p>
      <button class="btn btn--danger" type="button" disabled>Delete all my data</button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import ProviderKeyCard from '@/components/settings/ProviderKeyCard.vue'
import ProviderModelSelections from '@/components/settings/ProviderModelSelections.vue'
import providersApi from '@/api/providers'
import modelSelectionsApi from '@/api/modelSelections'
import { useAuth } from '@/stores/auth'
import { describeApiError } from '@/utils/errors'
import { formatDateTime } from '@/utils/time'
import {
  WRAP_MODELS,
  getDefaultWrapModel,
  setDefaultWrapModel
} from '@/utils/wrapModelPref'

const router = useRouter()
const auth = useAuth()

const loggingOut = ref(false)
const user = computed(() => auth.user.value)
const initial = computed(() => {
  const e = user.value?.email || ''
  return e ? e[0].toUpperCase() : '?'
})

const providers = ref([])
const statuses = ref({})
const loadingProviders = ref(true)
const loadError = ref(null)

const modelsByProvider = ref({})
const loadingModels = ref(true)

// Default wrap model — frontend-only preference, read once on mount.
const defaultWrapModel = ref(getDefaultWrapModel())
const wrapModelSaved = ref(false)
let wrapModelSavedTimer = null

function onWrapModelChange(next) {
  if (!next || next === defaultWrapModel.value) return
  if (!setDefaultWrapModel(next)) return
  defaultWrapModel.value = next
  // Brief confirmation that the change took effect — the storage
  // write is synchronous so we can flash the feedback immediately.
  wrapModelSaved.value = true
  if (wrapModelSavedTimer) clearTimeout(wrapModelSavedTimer)
  wrapModelSavedTimer = setTimeout(() => {
    wrapModelSaved.value = false
    wrapModelSavedTimer = null
  }, 1800)
}

const configuredProviders = computed(() =>
  providers.value.filter((p) => statuses.value[p.id]?.configured)
)

async function loadProviders() {
  loadingProviders.value = true
  loadError.value = null
  try {
    const data = await providersApi.list()
    providers.value = data?.providers || []
    statuses.value = (data?.configured || []).reduce((acc, s) => {
      acc[s.provider] = s
      return acc
    }, {})
  } catch (err) {
    loadError.value = describeApiError(err, 'Could not load provider settings.')
  } finally {
    loadingProviders.value = false
  }
}

async function loadModelSelections() {
  loadingModels.value = true
  try {
    const data = await modelSelectionsApi.list()
    modelsByProvider.value = data?.by_provider || {}
  } catch (_err) {
    // Non-fatal — user can still add keys; section will just appear empty.
    modelsByProvider.value = {}
  } finally {
    loadingModels.value = false
  }
}

function onProviderSaved({ provider, status }) {
  if (status) statuses.value = { ...statuses.value, [provider]: status }
  auth.refresh().catch(() => {})
}

function onProviderRemoved({ provider, status }) {
  if (status) statuses.value = { ...statuses.value, [provider]: status }
  auth.refresh().catch(() => {})
}

function onModelsChanged() {
  // Simplest correct thing: reload the selection map from the server.
  // These endpoints are cheap (small rows); no need to hand-merge.
  loadModelSelections()
}

async function onLogout() {
  loggingOut.value = true
  try {
    await auth.logout()
    router.replace({ name: 'login' })
  } finally {
    loggingOut.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadProviders(), loadModelSelections()])
})
</script>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.account-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.account-row__avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  flex-shrink: 0;
}

.account-row__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.account-row__label {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--color-text-muted);
}

.account-row__email {
  font-size: var(--text-base);
  font-weight: 500;
  word-break: break-all;
}

.account-row__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.provider-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.provider-cards__loading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0;
}

.banner {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  font-size: var(--text-sm);
  align-items: center;
}

.banner strong {
  font-weight: 600;
}

.banner--empty {
  background: var(--color-surface-muted);
  border-style: dashed;
  color: var(--color-text-secondary);
}

/* Section frame shared by the three "model"-flavored cards. The badge
   gives the user a sense of "do these in order" without prescribing a
   wizard layout. */
.settings-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.settings-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.settings-section__badge {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
}

.settings-section__hint {
  margin: 0 0 var(--space-3);
}

.settings-section__feedback {
  margin: var(--space-2) 0 0;
  font-size: var(--text-xs);
  color: var(--color-primary);
  font-weight: 500;
}

/* Wrap model radio list. Same row affordance as ProviderKeyCard so the
   three "model" cards visually rhyme. */
.wrap-model-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.wrap-model-option {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: pointer;
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.wrap-model-option:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-muted);
}

.wrap-model-option--active {
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.wrap-model-option input[type='radio'] {
  flex-shrink: 0;
}

.wrap-model-option__text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.wrap-model-option__label {
  font-weight: 500;
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}

.wrap-model-option__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.wrap-model-option__id {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  background: var(--color-surface-muted);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}

@media (max-width: 560px) {
  .account-row {
    flex-direction: column;
    align-items: flex-start;
  }
  .account-row .btn {
    width: 100%;
  }
}
</style>
