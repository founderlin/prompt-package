<template>
  <div class="settings-view">
    <PageHeader
      title="Settings"
      description="Configure your account, your LLM provider keys, and privacy preferences."
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

    <section class="card">
      <h3 class="card__title card__title--sm">LLM provider keys</h3>
      <p class="text-secondary" style="margin: 0 0 var(--space-3)">
        Bring your own keys. Configure one or more — every conversation
        picks its provider from the model dropdown.
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

    <section class="card">
      <h3 class="card__title card__title--sm">Available models</h3>
      <p class="text-secondary" style="margin: 0 0 var(--space-3)">
        Pick the models you want to see in the chat's model picker. Each
        provider is independent — you can enable several from OpenRouter,
        DeepSeek, and OpenAI at the same time.
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
