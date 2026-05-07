/**
 * Safe markdown → HTML renderer for chat replies.
 *
 * Pipeline:
 *   raw markdown → marked (parse) → DOMPurify (sanitize) → HTML string
 *
 * Code fences get syntax-highlighted via highlight.js. We wrap each block
 * in a small container so the bubble component can attach a "Copy" button
 * on top of it using event delegation (see MessageBubble.vue).
 *
 * Copy button: the click handler in MessageBubble.vue reads the visible
 * source straight out of the rendered <pre><code>'s textContent — we
 * don't embed the raw source in a data-* attribute, so "copy this block"
 * strictly means "copy what's visible in this block".
 *
 * Security:
 *   - DOMPurify strips anything that could execute script.
 *   - Links open in a new tab with rel="noopener noreferrer" to avoid
 *     tabnabbing.
 */

import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'

// Configure marked once. `gfm: true` turns on tables, strikethrough,
// task lists, etc.; `breaks: true` converts lone \n to <br> which matches
// how chat models format casual replies.
marked.setOptions({
  gfm: true,
  breaks: true,
  headerIds: false,
  mangle: false
})

// Custom renderer so we can (a) inject a highlighted inner <code> with a
// language class and (b) stash the raw source on the <pre> element for
// the copy-to-clipboard handler.
const renderer = new marked.Renderer()

// Languages we trust highlight.js to auto-detect for *unlabeled* fences.
// The default auto-detect list includes many exotic grammars that love to
// claim short / ambiguous snippets — TypeScript in particular is a frequent
// false positive for plain prose. Restricting the subset + requiring a
// minimum relevance score keeps ordinary text out of the language-styled
// path.
const AUTO_DETECT_LANGS = [
  'bash',
  'shell',
  'json',
  'yaml',
  'xml',
  'html',
  'css',
  'diff',
  'sql',
  'python',
  'javascript',
  'typescript',
  'java',
  'c',
  'cpp',
  'csharp',
  'go',
  'rust',
  'ruby',
  'php',
  'markdown'
]
const AUTO_DETECT_MIN_RELEVANCE = 8

// Heuristic: does this string look like prose rather than code? Used to
// short-circuit auto-detect for plain English answers that happened to be
// wrapped in a fence or 4-space-indented by the model. If true, we render
// as plaintext instead of feeding it to highlight.js.
function looksLikeProse(raw) {
  const text = String(raw)
  if (!text.trim()) return true
  // Very short snippets carry almost no signal; treat them as plaintext
  // rather than risk a bogus language guess.
  if (text.length < 40) return true
  // No obvious code punctuation? Almost certainly prose.
  const codeish = /[{};=<>]|\b(function|const|let|var|class|import|export|def|return|if|else|for|while)\b/
  if (!codeish.test(text)) return true
  return false
}

// marked v5+ passes a single token object to renderer methods
// (`{ type, raw, text, lang, ... }`). Older versions passed positional
// args `(code, infostring, escaped)`. Accept both so we keep working
// regardless of which major version the app is pinned to.
renderer.code = function (codeOrToken, infostring) {
  let raw
  let langRaw
  if (codeOrToken && typeof codeOrToken === 'object') {
    // marked v5+ token form.
    raw = typeof codeOrToken.text === 'string' ? codeOrToken.text : ''
    langRaw = typeof codeOrToken.lang === 'string' ? codeOrToken.lang : ''
  } else {
    // Legacy (code, infostring) positional form.
    raw = typeof codeOrToken === 'string' ? codeOrToken : ''
    langRaw = typeof infostring === 'string' ? infostring : ''
  }
  langRaw = langRaw.trim().split(/\s+/)[0] || ''
  const lang = langRaw.toLowerCase()

  let highlighted
  let detectedLang = lang
  try {
    if (lang && hljs.getLanguage(lang)) {
      // Explicit language on the fence — trust it.
      highlighted = hljs.highlight(raw, { language: lang, ignoreIllegals: true }).value
    } else if (looksLikeProse(raw)) {
      // Plain text / prose that got wrapped in a fence. Don't label it as
      // any language — render as plaintext so it doesn't show up with a
      // spurious "typescript" (or similar) badge.
      highlighted = escapeHtml(raw)
      detectedLang = ''
    } else {
      // Auto-detect, but only against a vetted subset and only accept the
      // result if highlight.js is confident enough. Otherwise fall back to
      // plaintext — a wrong label is worse than no label.
      const auto = hljs.highlightAuto(raw, AUTO_DETECT_LANGS)
      if (auto && auto.language && auto.relevance >= AUTO_DETECT_MIN_RELEVANCE) {
        highlighted = auto.value
        detectedLang = auto.language
      } else {
        highlighted = escapeHtml(raw)
        detectedLang = ''
      }
    }
  } catch (_err) {
    highlighted = escapeHtml(raw)
    detectedLang = ''
  }

  const langLabel = detectedLang ? escapeHtml(detectedLang) : ''

  // The copy button deliberately carries NO inlined source (no
  // `data-code` / base64 payload). The click handler reads the rendered
  // <code>'s textContent instead — that guarantees "what the user sees
  // in this block is what gets copied", with zero risk of the attribute
  // diverging from the visible content (which previously could happen
  // if marked merged content across fences, if sanitization altered the
  // attribute, or if the base64 decode went wrong).
  return (
    `<div class="md-codeblock">` +
    `<div class="md-codeblock__header">` +
    `<span class="md-codeblock__lang">${langLabel || 'code'}</span>` +
    `<button type="button" class="md-codeblock__copy" data-copy-code aria-label="Copy code">` +
    `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
    `<rect x="9" y="9" width="13" height="13" rx="2"/>` +
    `<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>` +
    `</svg>` +
    `<span class="md-codeblock__copy-label">Copy</span>` +
    `</button>` +
    `</div>` +
    `<pre class="md-codeblock__pre"><code class="hljs${detectedLang ? ` language-${escapeHtml(detectedLang)}` : ''}">${highlighted}</code></pre>` +
    `</div>`
  )
}

// Ensure every external link opens in a new tab safely. Accepts both the
// marked v5+ token form (`{ href, title, text, tokens }`) and the legacy
// positional form `(href, title, text)`.
renderer.link = function (hrefOrToken, title, text) {
  let href
  let linkTitle
  let linkText
  if (hrefOrToken && typeof hrefOrToken === 'object') {
    href = typeof hrefOrToken.href === 'string' ? hrefOrToken.href : ''
    linkTitle = typeof hrefOrToken.title === 'string' ? hrefOrToken.title : ''
    // Prefer parsed inline HTML (keeps nested markdown like **bold** / code
    // spans working); fall back to the plain text the tokenizer captured.
    if (Array.isArray(hrefOrToken.tokens) && this?.parser?.parseInline) {
      linkText = this.parser.parseInline(hrefOrToken.tokens)
    } else {
      linkText = escapeHtml(
        typeof hrefOrToken.text === 'string' ? hrefOrToken.text : ''
      )
    }
  } else {
    href = typeof hrefOrToken === 'string' ? hrefOrToken : ''
    linkTitle = typeof title === 'string' ? title : ''
    // In the legacy form `text` is already rendered HTML.
    linkText = typeof text === 'string' ? text : ''
  }
  const safeTitle = linkTitle ? ` title="${escapeHtml(linkTitle)}"` : ''
  return (
    `<a href="${escapeHtml(href)}"${safeTitle} target="_blank" rel="noopener noreferrer">` +
    `${linkText}</a>`
  )
}

marked.use({ renderer })

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const PURIFY_CONFIG = {
  // Keep inline markdown-ish attributes we set ourselves. `data-copy-code`
  // is still used as a CSS/selector hook on the copy button (event
  // delegation in MessageBubble reads it). `data-code` was removed —
  // copying now uses the <code> element's textContent directly.
  ADD_ATTR: ['target', 'rel', 'data-copy-code'],
  // Keep <br> / <hr> / tables / blockquotes / code / pre / etc.
  // (DOMPurify's defaults already allow those.)
  FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form'],
  FORBID_ATTR: ['onerror', 'onclick', 'onload']
}

/**
 * Balance unclosed triple-backtick (and tilde) fences.
 *
 * LLM replies occasionally open a code fence and forget to close it —
 * either because the model got cut off, or because its output contains
 * only an opening ``` with no matching closer. Vanilla marked reacts to
 * this by swallowing everything from the opener to the end of the input
 * into ONE giant code block. That breaks two things at once:
 *   (a) the rest of the reply stops rendering (no headings / paragraphs /
 *       other code blocks — they all show up inside the unclosed fence).
 *   (b) Copy on that code block copies the entire swallowed tail, which
 *       is what the user reported as "Copy copies the whole conversation".
 *
 * We scan line-by-line counting fence toggles. If the count is odd at the
 * end, we append a closing fence so marked can terminate the block
 * cleanly. We ignore indented code (4-space / tab) here — those don't
 * have fences to mismatch.
 */
function balanceCodeFences(src) {
  const lines = src.split('\n')
  let openFence = null // null | '```' | '~~~'
  for (const line of lines) {
    // Match a fence at the start of the line (allow up to 3 leading
    // spaces — marked follows CommonMark here). We only care about
    // fences of 3+ backticks or 3+ tildes. The info string after the
    // opener is irrelevant for pairing.
    const m = /^ {0,3}(`{3,}|~{3,})/.exec(line)
    if (!m) continue
    const marker = m[1][0] === '`' ? '```' : '~~~'
    if (openFence === null) {
      openFence = marker
    } else if (openFence === marker) {
      // A matching closer. (Strict CommonMark also requires the closer's
      // length to be ≥ opener's length, but for the sake of "don't eat
      // the rest of the reply" a looser match is safer.)
      openFence = null
    }
    // If openFence is set to one marker and we see the other marker, it
    // does NOT close — leave openFence as-is.
  }
  if (openFence !== null) {
    // Add a newline if the source doesn't already end with one, so the
    // auto-added closer sits on its own line.
    const prefix = src.endsWith('\n') ? '' : '\n'
    return src + prefix + openFence + '\n'
  }
  return src
}

/**
 * Render untrusted markdown to sanitized HTML. Always safe to pass to v-html.
 */
export function renderMarkdown(source) {
  if (source == null) return ''
  const text = String(source)
  if (!text.trim()) return ''
  const balanced = balanceCodeFences(text)
  const html = marked.parse(balanced)
  return DOMPurify.sanitize(html, PURIFY_CONFIG)
}

export default renderMarkdown
