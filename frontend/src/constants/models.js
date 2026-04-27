/**
 * Curated multi-provider model catalogue (R14).
 *
 * Each option carries TWO orthogonal labels:
 *
 *   - ``provider`` — which API gateway runs the model
 *     ('openrouter' | 'deepseek' | 'openai'). Drives which API key the
 *     backend will reach for, and which dropdown group the option is
 *     shown under.
 *   - ``vendor``   — which lab actually trained the model
 *     ('OpenAI' / 'Anthropic' / 'Google' / etc.). Display-only.
 *
 * Users can also pick "Custom" to paste any model id themselves; for
 * Custom we default the provider to 'openrouter' (the only catalogue
 * we don't curate exhaustively).
 *
 * Keep this list small and current. Refer to
 * https://openrouter.ai/models for the OpenRouter catalogue.
 */
export const PROVIDERS = [
  {
    id: 'openrouter',
    label: 'OpenRouter',
    description:
      'One key, dozens of vendors. Easy way to try Claude, Gemini, Llama, etc.'
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    description:
      'Direct DeepSeek API. Strong reasoning at a low price point.'
  },
  {
    id: 'openai',
    label: 'OpenAI',
    description:
      'Direct OpenAI API. Use this if you already pay OpenAI and want lowest latency.'
  }
]

export const PROVIDER_LABELS = PROVIDERS.reduce((acc, p) => {
  acc[p.id] = p.label
  return acc
}, {})

export const MODEL_OPTIONS = [
  // ── OpenRouter ─────────────────────────────────────────────────────
  {
    id: 'openai/gpt-4o-mini',
    label: 'GPT-4o mini',
    vendor: 'OpenAI',
    provider: 'openrouter',
    hint: 'Fast, cheap default.'
  },
  {
    id: 'openai/gpt-4o',
    label: 'GPT-4o',
    vendor: 'OpenAI',
    provider: 'openrouter',
    hint: 'Stronger reasoning, higher cost.'
  },
  {
    id: 'anthropic/claude-3.5-sonnet',
    label: 'Claude 3.5 Sonnet',
    vendor: 'Anthropic',
    provider: 'openrouter',
    hint: 'Excellent writing & long-context.'
  },
  {
    id: 'anthropic/claude-3.5-haiku',
    label: 'Claude 3.5 Haiku',
    vendor: 'Anthropic',
    provider: 'openrouter',
    hint: 'Fast, inexpensive Anthropic option.'
  },
  {
    id: 'google/gemini-2.0-flash-001',
    label: 'Gemini 2.0 Flash',
    vendor: 'Google',
    provider: 'openrouter',
    hint: 'Fast multimodal Google model.'
  },
  {
    id: 'meta-llama/llama-3.1-70b-instruct',
    label: 'Llama 3.1 70B Instruct',
    vendor: 'Meta',
    provider: 'openrouter',
    hint: 'Strong open-weight option.'
  },
  // ── DeepSeek (direct) ──────────────────────────────────────────────
  {
    id: 'deepseek-chat',
    label: 'DeepSeek Chat',
    vendor: 'DeepSeek',
    provider: 'deepseek',
    hint: 'General-purpose, low cost.'
  },
  {
    id: 'deepseek-reasoner',
    label: 'DeepSeek Reasoner',
    vendor: 'DeepSeek',
    provider: 'deepseek',
    hint: 'Chain-of-thought style reasoning.'
  },
  // ── OpenAI (direct) ────────────────────────────────────────────────
  {
    id: 'gpt-4o-mini',
    label: 'GPT-4o mini',
    vendor: 'OpenAI',
    provider: 'openai',
    hint: 'Cheap, fast default.'
  },
  {
    id: 'gpt-4o',
    label: 'GPT-4o',
    vendor: 'OpenAI',
    provider: 'openai',
    hint: 'Top-end multimodal model.'
  },
  {
    id: 'gpt-4.1-mini',
    label: 'GPT-4.1 mini',
    vendor: 'OpenAI',
    provider: 'openai',
    hint: 'Newer, cheaper general purpose.'
  },
  {
    id: 'o1-mini',
    label: 'o1-mini',
    vendor: 'OpenAI',
    provider: 'openai',
    hint: 'Reasoning-tuned, slower & pricier.'
  }
]

export const DEFAULT_PROVIDER = 'openrouter'
export const DEFAULT_MODEL_ID = 'openai/gpt-4o-mini'

export function findModelOption(modelId, provider) {
  if (!modelId) return null
  if (provider) {
    const exact = MODEL_OPTIONS.find(
      (m) => m.id === modelId && m.provider === provider
    )
    if (exact) return exact
  }
  return MODEL_OPTIONS.find((m) => m.id === modelId) || null
}

export function modelLabel(modelId, provider) {
  const found = findModelOption(modelId, provider)
  return found ? found.label : modelId || 'Unknown model'
}

export function providerLabel(providerId) {
  if (!providerId) return PROVIDER_LABELS[DEFAULT_PROVIDER]
  return PROVIDER_LABELS[providerId] || providerId
}

/**
 * Group MODEL_OPTIONS by provider for the dropdown <optgroup> rendering.
 * Returns ``[{ provider: 'openrouter', label: 'OpenRouter', options: [...] }, ...]``.
 */
export function groupedModelOptions() {
  return PROVIDERS.map((p) => ({
    provider: p.id,
    label: p.label,
    options: MODEL_OPTIONS.filter((m) => m.provider === p.id)
  }))
}
