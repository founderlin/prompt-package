<template>
  <AuthLayout>
    <section class="auth-card">
      <header class="auth-card__header">
        <h1 class="auth-card__title">Welcome back</h1>
        <p class="auth-card__subtitle">Sign in to continue with your AI project memory.</p>
      </header>

      <div v-if="googleEnabled" class="auth-card__sso">
        <GoogleSignInButton
          text="signin_with"
          width="352"
          @credential="onGoogleCredential"
          @error="onGoogleError"
        />
        <p v-if="googleError" class="auth-form__error auth-form__error--inline">
          {{ googleError }}
        </p>
        <div class="auth-card__divider">
          <span>or sign in with email</span>
        </div>
      </div>

      <form class="auth-form" @submit.prevent="onSubmit" novalidate>
        <div class="field">
          <label for="login-email" class="field__label">Email</label>
          <input
            id="login-email"
            v-model.trim="email"
            type="email"
            class="input"
            autocomplete="email"
            required
            :disabled="submitting"
            placeholder="you@example.com"
          />
        </div>

        <div class="field">
          <label for="login-password" class="field__label">Password</label>
          <input
            id="login-password"
            v-model="password"
            type="password"
            class="input"
            autocomplete="current-password"
            required
            :disabled="submitting"
            placeholder="At least 8 characters"
          />
        </div>

        <p v-if="errorMessage" class="auth-form__error">{{ errorMessage }}</p>

        <button
          class="btn btn--primary btn--lg auth-form__submit"
          :disabled="submitting"
          type="submit"
        >
          <span v-if="submitting" class="spinner" aria-hidden="true" />
          <span>{{ submitting ? 'Signing in…' : 'Sign in' }}</span>
        </button>

        <p class="auth-form__switch">
          New here?
          <RouterLink :to="{ name: 'register', query: $route.query }">Create an account</RouterLink>
        </p>
      </form>
    </section>
  </AuthLayout>
</template>

<script setup>
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AuthLayout from '@/layouts/AuthLayout.vue'
import GoogleSignInButton from '@/components/auth/GoogleSignInButton.vue'
import { useAuth } from '@/stores/auth'
import { describeApiError } from '@/utils/errors'

const route = useRoute()
const router = useRouter()
const auth = useAuth()

const email = ref('')
const password = ref('')
const submitting = ref(false)
const errorMessage = ref('')
const googleError = ref('')

const googleEnabled = computed(() => Boolean(import.meta.env.VITE_GOOGLE_CLIENT_ID))

function redirectAfterAuth() {
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : null
  router.replace(redirect || { name: 'dashboard' })
}

async function onSubmit() {
  errorMessage.value = ''
  if (!email.value || !password.value) {
    errorMessage.value = 'Please enter both your email and password.'
    return
  }
  submitting.value = true
  try {
    await auth.login(email.value, password.value)
    redirectAfterAuth()
  } catch (err) {
    errorMessage.value = describeApiError(err, 'Could not sign you in.')
  } finally {
    submitting.value = false
  }
}

async function onGoogleCredential(idToken) {
  googleError.value = ''
  errorMessage.value = ''
  submitting.value = true
  try {
    await auth.loginWithGoogle(idToken)
    redirectAfterAuth()
  } catch (err) {
    googleError.value = describeApiError(err, 'Could not sign in with Google.')
  } finally {
    submitting.value = false
  }
}

function onGoogleError(err) {
  googleError.value = err?.message || 'Google sign-in failed to load.'
}
</script>

<style scoped>
.auth-card {
  width: 100%;
  max-width: 400px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-2);
  padding: var(--space-6);
}

.auth-card__header {
  margin-bottom: var(--space-5);
}

.auth-card__title {
  font-size: var(--text-2xl);
  font-weight: 500;
  margin: 0 0 var(--space-1);
}

.auth-card__subtitle {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
}

.auth-card__sso {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.auth-card__divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.auth-card__divider::before,
.auth-card__divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}

.auth-form__error--inline {
  margin: 0;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.auth-form__error {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  background: var(--color-error-soft);
  color: var(--color-error);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}

.auth-form__submit {
  width: 100%;
  margin-top: var(--space-1);
}

.auth-form__switch {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-align: center;
}
</style>
