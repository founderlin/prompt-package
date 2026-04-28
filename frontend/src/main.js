import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/base.css'
// highlight.js theme for rendered code blocks inside chat bubbles.
// GitHub-style theme matches the rest of the UI's light/neutral palette.
import 'highlight.js/styles/github.css'
// Browser tab / PWA favicon — square "mark" variant of the logo.
// icon1.png is the full-resolution (1014x1014) source; the favicon-N
// variants are pre-scaled so tab renderers can pick the right size
// without blurry on-the-fly resampling.
import faviconFull from './icon1.png'
import favicon192 from './favicon-192.png'
import favicon96 from './favicon-96.png'
import favicon48 from './favicon-48.png'

const app = createApp(App)
app.use(router)

function applySiteBrandAssets() {
  // Remove any stale icon <link> tags that a previous build (or the
  // inline <link rel="icon"> in index.html) left behind, then install
  // fresh ones at multiple sizes so browsers / OSes pick the sharpest
  // option per context (tab, bookmark, Add-to-Home-Screen, etc.).
  document
    .querySelectorAll('link[rel="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]')
    .forEach((node) => node.parentNode?.removeChild(node))

  const variants = [
    { rel: 'icon', type: 'image/png', sizes: '48x48', href: favicon48 },
    { rel: 'icon', type: 'image/png', sizes: '96x96', href: favicon96 },
    { rel: 'icon', type: 'image/png', sizes: '192x192', href: favicon192 },
    // Apple home-screen icon. iOS ignores the `sizes` attribute but
    // takes the highest-resolution <link rel="apple-touch-icon">.
    { rel: 'apple-touch-icon', type: 'image/png', sizes: '192x192', href: favicon192 },
    // Last-resort fallback: original unscaled source. Browsers that
    // don't understand `sizes` will fall through to this one.
    { rel: 'icon', type: 'image/png', href: faviconFull }
  ]
  for (const v of variants) {
    const link = document.createElement('link')
    link.rel = v.rel
    link.type = v.type
    if (v.sizes) link.sizes = v.sizes
    link.href = v.href
    document.head.appendChild(link)
  }
}
applySiteBrandAssets()

// Wait for the first navigation (which triggers the auth `init`) before
// mounting so we don't flash a protected page when the user is logged out.
router.isReady().then(() => {
  app.mount('#app')
})
