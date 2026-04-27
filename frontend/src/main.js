import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/base.css'
import logoHref from './icon.jpeg'

const app = createApp(App)
app.use(router)

function applySiteBrandAssets() {
  const existing = document.querySelector("link[rel='icon']")
  const icon = existing || document.createElement('link')
  icon.rel = 'icon'
  icon.type = 'image/jpeg'
  icon.href = logoHref
  if (!existing) document.head.appendChild(icon)
}
applySiteBrandAssets()

// Wait for the first navigation (which triggers the auth `init`) before
// mounting so we don't flash a protected page when the user is logged out.
router.isReady().then(() => {
  app.mount('#app')
})
