<template>
  <div v-if="enabled" class="google-signin">
    <div ref="buttonHost" class="google-signin__button" />
    <p v-if="loadError" class="google-signin__error" role="alert">
      {{ loadError }}
    </p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  // Visible label on the button. GIS supports: 'signin_with', 'signup_with',
  // 'continue_with', 'signin'.
  text: {
    type: String,
    default: 'continue_with'
  },
  // GIS button width in CSS pixels. Empty string lets GIS auto-size.
  width: {
    type: [Number, String],
    default: ''
  }
})

const emit = defineEmits(['credential', 'error'])

const clientId = computed(() => import.meta.env.VITE_GOOGLE_CLIENT_ID || '')
const enabled = computed(() => Boolean(clientId.value))

const buttonHost = ref(null)
const loadError = ref('')

const GIS_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
let scriptPromise = null

function loadGisScript() {
  if (scriptPromise) return scriptPromise
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('Window unavailable'))
  }
  if (window.google?.accounts?.id) {
    scriptPromise = Promise.resolve()
    return scriptPromise
  }
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${GIS_SCRIPT_SRC}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener(
        'error',
        () => reject(new Error('Failed to load Google Identity Services.')),
        { once: true }
      )
      return
    }
    const script = document.createElement('script')
    script.src = GIS_SCRIPT_SRC
    script.async = true
    script.defer = true
    script.onload = () => resolve()
    script.onerror = () =>
      reject(new Error('Failed to load Google Identity Services.'))
    document.head.appendChild(script)
  })
  return scriptPromise
}

let initialized = false

function handleCredentialResponse(response) {
  if (!response?.credential) {
    emit('error', new Error('Google did not return a credential.'))
    return
  }
  emit('credential', response.credential)
}

async function bootstrap() {
  if (!enabled.value) return
  loadError.value = ''
  try {
    await loadGisScript()
  } catch (err) {
    loadError.value = err.message || 'Could not load Google sign-in.'
    emit('error', err)
    return
  }
  if (!window.google?.accounts?.id) {
    loadError.value = 'Google sign-in is unavailable right now.'
    return
  }
  if (!initialized) {
    window.google.accounts.id.initialize({
      client_id: clientId.value,
      callback: handleCredentialResponse,
      auto_select: false,
      ux_mode: 'popup'
    })
    initialized = true
  }
  if (!buttonHost.value) return
  // Empty the host before re-rendering to avoid stacking buttons on
  // hot-reload / re-mount.
  buttonHost.value.innerHTML = ''
  const renderOpts = {
    type: 'standard',
    theme: 'outline',
    size: 'large',
    shape: 'rectangular',
    logo_alignment: 'left',
    text: props.text
  }
  if (props.width) renderOpts.width = String(props.width)
  window.google.accounts.id.renderButton(buttonHost.value, renderOpts)
}

onMounted(bootstrap)
watch(() => clientId.value, bootstrap)

onBeforeUnmount(() => {
  if (window.google?.accounts?.id?.cancel) {
    try {
      window.google.accounts.id.cancel()
    } catch (_e) {
      /* GIS not initialized — nothing to cancel */
    }
  }
})
</script>

<style scoped>
.google-signin {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
}

.google-signin__button {
  display: flex;
  justify-content: center;
  /* GIS injects an iframe sized to the renderButton width option; centering
     keeps it tidy if the parent is wider. */
  min-height: 40px;
}

.google-signin__error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-error);
  text-align: center;
}
</style>
