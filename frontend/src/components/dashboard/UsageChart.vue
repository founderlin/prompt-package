<template>
  <div class="usage-chart">
    <header class="usage-chart__header">
      <div class="usage-chart__title-block">
        <h3 class="usage-chart__title">Token usage &amp; cost</h3>
        <p class="usage-chart__subtitle">
          <template v-if="loading">Crunching your numbers…</template>
          <template v-else-if="!summary">No data yet</template>
          <template v-else>
            <span class="usage-chart__sparkle" aria-hidden="true">✨</span>
            {{ formatTokens(summary.totals.total_tokens) }} tokens ·
            <strong>${{ formatCost(summary.totals.cost_usd) }}</strong>
            in the last {{ windowLabel }}
          </template>
        </p>
      </div>

      <div class="usage-chart__controls" role="tablist" aria-label="Granularity">
        <button
          v-for="g in granularities"
          :key="g.id"
          type="button"
          role="tab"
          class="usage-chart__tab"
          :class="{ 'usage-chart__tab--active': current === g.id }"
          :aria-selected="current === g.id"
          :disabled="loading"
          @click="$emit('change', g.id)"
        >
          {{ g.label }}
        </button>
      </div>
    </header>

    <div v-if="error" class="usage-chart__error">
      <span>{{ error }}</span>
      <button
        type="button"
        class="btn btn--ghost btn--sm"
        @click="$emit('retry')"
      >
        Retry
      </button>
    </div>

    <div v-else class="usage-chart__body">
      <!-- Metric toggle (Tokens / Cost) -->
      <div class="usage-chart__metrics">
        <button
          type="button"
          class="usage-metric"
          :class="{ 'usage-metric--on': metric === 'tokens' }"
          @click="metric = 'tokens'"
        >
          <span class="usage-metric__swatch usage-metric__swatch--tokens" />
          <span class="usage-metric__label">Tokens</span>
          <span class="usage-metric__value">
            {{
              summary
                ? formatTokens(summary.totals.total_tokens)
                : '—'
            }}
          </span>
        </button>
        <button
          type="button"
          class="usage-metric"
          :class="{ 'usage-metric--on': metric === 'cost' }"
          @click="metric = 'cost'"
        >
          <span class="usage-metric__swatch usage-metric__swatch--cost" />
          <span class="usage-metric__label">Cost</span>
          <span class="usage-metric__value">
            ${{
              summary
                ? formatCost(summary.totals.cost_usd)
                : '0.00'
            }}
          </span>
        </button>
        <div class="usage-metric usage-metric--inert">
          <span class="usage-metric__label">Turns</span>
          <span class="usage-metric__value">
            {{ summary ? summary.totals.message_count : 0 }}
          </span>
        </div>
      </div>

      <!-- SVG chart -->
      <div class="usage-chart__svg-wrap" ref="wrapRef">
        <svg
          v-if="viewBoxW > 0"
          :viewBox="`0 0 ${viewBoxW} ${viewBoxH}`"
          preserveAspectRatio="none"
          class="usage-chart__svg"
          @mouseleave="hoverIdx = null"
          @mousemove="onMove"
        >
          <!-- Cute gradients -->
          <defs>
            <linearGradient id="barTokens" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#8B5CF6" stop-opacity="0.95" />
              <stop offset="100%" stop-color="#6366F1" stop-opacity="0.85" />
            </linearGradient>
            <linearGradient id="barCost" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#F59E0B" stop-opacity="0.95" />
              <stop offset="100%" stop-color="#EF4444" stop-opacity="0.85" />
            </linearGradient>
            <linearGradient id="lineTokens" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#8B5CF6" stop-opacity="0.35" />
              <stop offset="100%" stop-color="#8B5CF6" stop-opacity="0" />
            </linearGradient>
            <linearGradient id="lineCost" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#F59E0B" stop-opacity="0.35" />
              <stop offset="100%" stop-color="#F59E0B" stop-opacity="0" />
            </linearGradient>
            <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <!-- Horizontal grid lines -->
          <g class="usage-chart__grid">
            <line
              v-for="(y, i) in gridLines"
              :key="i"
              :x1="padding.left"
              :x2="viewBoxW - padding.right"
              :y1="y"
              :y2="y"
            />
          </g>

          <!-- Axis labels (y max/min) -->
          <g class="usage-chart__axis">
            <text
              :x="padding.left - 6"
              :y="padding.top + 4"
              text-anchor="end"
            >
              {{ formatMetric(maxValue) }}
            </text>
            <text
              :x="padding.left - 6"
              :y="viewBoxH - padding.bottom + 2"
              text-anchor="end"
            >
              0
            </text>
          </g>

          <!-- Baseline area fill -->
          <path
            v-if="areaPath"
            :d="areaPath"
            :fill="metric === 'tokens' ? 'url(#lineTokens)' : 'url(#lineCost)'"
            class="usage-chart__area"
          />

          <!-- Bars -->
          <g class="usage-chart__bars">
            <rect
              v-for="(bar, i) in bars"
              :key="i"
              :x="bar.x"
              :y="bar.y"
              :width="bar.w"
              :height="bar.h"
              :rx="Math.min(bar.w / 2, 4)"
              :ry="Math.min(bar.w / 2, 4)"
              :fill="metric === 'tokens' ? 'url(#barTokens)' : 'url(#barCost)'"
              :class="{
                'usage-chart__bar--hover': hoverIdx === i,
                'usage-chart__bar--empty': bar.empty
              }"
              @mouseenter="hoverIdx = i"
            >
              <title>{{ bar.tooltip }}</title>
            </rect>
          </g>

          <!-- Top dots -->
          <g class="usage-chart__dots">
            <circle
              v-for="(bar, i) in bars"
              :key="`d-${i}`"
              :cx="bar.x + bar.w / 2"
              :cy="bar.y"
              r="3"
              :fill="metric === 'tokens' ? '#8B5CF6' : '#F59E0B'"
              :class="{
                'usage-chart__dot--hover': hoverIdx === i,
                'usage-chart__dot--hidden': bar.empty
              }"
              filter="url(#glow)"
            />
          </g>

          <!-- X-axis tick labels -->
          <g class="usage-chart__xticks">
            <text
              v-for="(tick, i) in xTicks"
              :key="`xt-${i}`"
              :x="tick.x"
              :y="viewBoxH - 4"
              text-anchor="middle"
            >
              {{ tick.label }}
            </text>
          </g>

          <!-- Hover guideline -->
          <line
            v-if="hoverIdx !== null && bars[hoverIdx]"
            class="usage-chart__guide"
            :x1="bars[hoverIdx].x + bars[hoverIdx].w / 2"
            :x2="bars[hoverIdx].x + bars[hoverIdx].w / 2"
            :y1="padding.top"
            :y2="viewBoxH - padding.bottom"
          />
        </svg>
      </div>

      <!-- Tooltip -->
      <div
        v-if="hoverIdx !== null && bars[hoverIdx]"
        class="usage-tooltip"
        :style="tooltipStyle"
      >
        <p class="usage-tooltip__title">
          {{ bars[hoverIdx].fullLabel }}
        </p>
        <dl class="usage-tooltip__grid">
          <div>
            <dt>Prompt</dt>
            <dd>{{ formatTokens(bars[hoverIdx].bucket.prompt_tokens) }}</dd>
          </div>
          <div>
            <dt>Completion</dt>
            <dd>{{ formatTokens(bars[hoverIdx].bucket.completion_tokens) }}</dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd>{{ formatTokens(bars[hoverIdx].bucket.total_tokens) }}</dd>
          </div>
          <div>
            <dt>Cost</dt>
            <dd>${{ formatCost(bars[hoverIdx].bucket.cost_usd) }}</dd>
          </div>
          <div>
            <dt>Turns</dt>
            <dd>{{ bars[hoverIdx].bucket.message_count }}</dd>
          </div>
        </dl>
      </div>

      <!-- Empty-state note overlay (when there truly is no data) -->
      <p
        v-if="!loading && summary && summary.totals.message_count === 0"
        class="usage-chart__empty"
      >
        <span aria-hidden="true">🌱</span>
        No token activity in this window yet — send a message from any
        project to fill this up.
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  summary: { type: Object, default: null },
  current: { type: String, default: 'day' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

defineEmits(['change', 'retry'])

const granularities = [
  { id: 'hour', label: 'Hour' },
  { id: 'day', label: 'Day' },
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' }
]

const metric = ref('tokens') // 'tokens' | 'cost'
const hoverIdx = ref(null)

const wrapRef = ref(null)
const viewBoxW = ref(640)
const viewBoxH = 220

const padding = { top: 16, right: 14, bottom: 22, left: 40 }

let ro = null

function measureWidth() {
  const el = wrapRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  // Clamp to something sane; viewBox scales with preserveAspectRatio=none.
  viewBoxW.value = Math.max(320, Math.floor(rect.width))
}

onMounted(() => {
  measureWidth()
  if (typeof ResizeObserver !== 'undefined' && wrapRef.value) {
    ro = new ResizeObserver(measureWidth)
    ro.observe(wrapRef.value)
  } else {
    window.addEventListener('resize', measureWidth)
  }
})

onBeforeUnmount(() => {
  if (ro) ro.disconnect()
  window.removeEventListener('resize', measureWidth)
})

const buckets = computed(() => props.summary?.buckets || [])

const values = computed(() =>
  buckets.value.map((b) =>
    metric.value === 'tokens' ? b.total_tokens : b.cost_usd
  )
)

const maxValue = computed(() => {
  const m = Math.max(0, ...values.value)
  return m === 0 ? (metric.value === 'tokens' ? 100 : 0.01) : m
})

const bars = computed(() => {
  const W = viewBoxW.value
  const chartW = W - padding.left - padding.right
  const chartH = viewBoxH - padding.top - padding.bottom
  const n = buckets.value.length
  if (n === 0) return []
  const slot = chartW / n
  const barW = Math.max(4, Math.min(slot - 6, 28))
  const gap = slot - barW

  const max = maxValue.value
  return buckets.value.map((b, i) => {
    const value = metric.value === 'tokens' ? b.total_tokens : b.cost_usd
    const hPct = max === 0 ? 0 : Math.max(0, Math.min(1, value / max))
    const h = Math.max(2, hPct * chartH)
    const x = padding.left + i * slot + gap / 2
    const y = padding.top + chartH - h
    return {
      x,
      y,
      w: barW,
      h,
      bucket: b,
      empty: value === 0,
      fullLabel: fullLabelForBucket(b, props.summary?.granularity || 'day'),
      tooltip: `${fullLabelForBucket(
        b,
        props.summary?.granularity || 'day'
      )}  •  ${formatTokens(b.total_tokens)} tokens  •  $${formatCost(b.cost_usd)}`
    }
  })
})

const areaPath = computed(() => {
  const bs = bars.value
  if (!bs.length) return ''
  const parts = []
  parts.push(`M ${bs[0].x + bs[0].w / 2} ${bs[0].y}`)
  for (let i = 1; i < bs.length; i++) {
    const p = bs[i - 1]
    const c = bs[i]
    const px = p.x + p.w / 2
    const cx = c.x + c.w / 2
    const mid = (px + cx) / 2
    // Smooth cubic-ish curve via two control points at mid x.
    parts.push(`C ${mid} ${p.y} ${mid} ${c.y} ${cx} ${c.y}`)
  }
  const last = bs[bs.length - 1]
  const bottom = viewBoxH - padding.bottom
  parts.push(`L ${last.x + last.w / 2} ${bottom}`)
  parts.push(`L ${bs[0].x + bs[0].w / 2} ${bottom}`)
  parts.push('Z')
  return parts.join(' ')
})

const gridLines = computed(() => {
  const chartH = viewBoxH - padding.top - padding.bottom
  const count = 4
  const lines = []
  for (let i = 0; i <= count; i++) {
    lines.push(padding.top + (chartH * i) / count)
  }
  return lines
})

const xTicks = computed(() => {
  const bs = bars.value
  if (!bs.length) return []
  const n = bs.length
  // Show roughly 5 ticks, evenly spaced. Always include first + last.
  const count = Math.min(5, n)
  const out = []
  for (let i = 0; i < count; i++) {
    const idx =
      count === 1 ? 0 : Math.round((i * (n - 1)) / (count - 1))
    const bar = bs[idx]
    out.push({
      x: bar.x + bar.w / 2,
      label: shortLabelForBucket(
        bar.bucket,
        props.summary?.granularity || 'day'
      )
    })
  }
  return out
})

const windowLabel = computed(() => {
  switch (props.current) {
    case 'hour':
      return '24 hours'
    case 'day':
      return '30 days'
    case 'week':
      return '12 weeks'
    case 'month':
      return '12 months'
    default:
      return 'window'
  }
})

const tooltipStyle = computed(() => {
  if (hoverIdx.value === null) return {}
  const bar = bars.value[hoverIdx.value]
  if (!bar) return {}
  const xPct = ((bar.x + bar.w / 2) / viewBoxW.value) * 100
  // Flip tooltip to the left if too close to right edge.
  const flip = xPct > 65
  return {
    left: flip ? 'auto' : `${xPct}%`,
    right: flip ? `${100 - xPct}%` : 'auto',
    transform: flip ? 'translate(-8px, 0)' : 'translate(8px, 0)'
  }
})

function onMove(event) {
  const svg = event.currentTarget
  if (!svg || !bars.value.length) return
  const rect = svg.getBoundingClientRect()
  const relX = event.clientX - rect.left
  // Map to viewBox x.
  const vbX = (relX / rect.width) * viewBoxW.value
  // Nearest bar by center distance.
  let best = 0
  let bestDist = Infinity
  for (let i = 0; i < bars.value.length; i++) {
    const bar = bars.value[i]
    const cx = bar.x + bar.w / 2
    const d = Math.abs(vbX - cx)
    if (d < bestDist) {
      best = i
      bestDist = d
    }
  }
  hoverIdx.value = best
}

watch(
  () => props.summary,
  () => {
    hoverIdx.value = null
  }
)

// ---- Formatting helpers ----------------------------------------------------

function formatMetric(v) {
  return metric.value === 'tokens' ? formatTokens(v) : `$${formatCost(v)}`
}

function formatTokens(n) {
  const x = Number(n) || 0
  if (x >= 1_000_000) return `${(x / 1_000_000).toFixed(1)}M`
  if (x >= 1_000) return `${(x / 1_000).toFixed(1)}K`
  return String(Math.round(x))
}

function formatCost(n) {
  const x = Number(n) || 0
  if (x === 0) return '0.00'
  if (x < 0.01) return x.toFixed(4)
  return x.toFixed(2)
}

function fullLabelForBucket(b, granularity) {
  const d = new Date(b.start)
  if (granularity === 'hour') {
    const hh = String(d.getHours()).padStart(2, '0')
    const ds = d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric'
    })
    return `${ds}, ${hh}:00`
  }
  if (granularity === 'month') {
    return d.toLocaleDateString(undefined, {
      month: 'long',
      year: 'numeric'
    })
  }
  if (granularity === 'week') {
    const end = new Date(b.end)
    end.setDate(end.getDate() - 1)
    const fmt = (x) =>
      x.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    return `${fmt(d)} – ${fmt(end)}`
  }
  return d.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric'
  })
}

function shortLabelForBucket(b, granularity) {
  const d = new Date(b.start)
  if (granularity === 'hour') {
    return `${String(d.getHours()).padStart(2, '0')}:00`
  }
  if (granularity === 'month') {
    return d.toLocaleDateString(undefined, { month: 'short' })
  }
  if (granularity === 'week') {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
</script>

<style scoped>
.usage-chart {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.usage-chart__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.usage-chart__title-block {
  flex: 1;
  min-width: 0;
}

.usage-chart__title {
  margin: 0 0 4px;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--color-text-primary);
}

.usage-chart__subtitle {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.usage-chart__subtitle strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.usage-chart__sparkle {
  display: inline-block;
  transform: translateY(-1px);
  margin-right: 2px;
}

/* Granularity tabs — playful pill group */
.usage-chart__controls {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  background: linear-gradient(
    135deg,
    rgba(139, 92, 246, 0.1),
    rgba(245, 158, 11, 0.1)
  );
  border: 1px solid var(--color-border);
}

.usage-chart__tab {
  background: transparent;
  border: none;
  padding: 6px 14px;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  border-radius: 999px;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease,
    transform 0.15s ease;
}

.usage-chart__tab:hover:not(:disabled) {
  color: var(--color-text-primary);
}

.usage-chart__tab--active {
  background: var(--color-surface);
  color: var(--color-text-primary);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06),
    0 1px 6px rgba(139, 92, 246, 0.18);
  transform: translateY(-1px);
}

.usage-chart__tab:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.usage-chart__error {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-error-soft);
  border: 1px solid rgba(217, 48, 37, 0.35);
  color: var(--color-error);
  font-size: var(--text-sm);
  align-items: center;
}

.usage-chart__body {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.usage-chart__metrics {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.usage-metric {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  cursor: pointer;
  font: inherit;
  font-size: var(--text-xs);
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.usage-metric:hover:not(:disabled) {
  border-color: var(--color-border-strong);
}

.usage-metric--on {
  background: var(--color-surface);
  border-color: rgba(139, 92, 246, 0.5);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.12);
}

.usage-metric--inert {
  cursor: default;
  opacity: 0.8;
}

.usage-metric__swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
}

.usage-metric__swatch--tokens {
  background: linear-gradient(135deg, #8b5cf6, #6366f1);
}

.usage-metric__swatch--cost {
  background: linear-gradient(135deg, #f59e0b, #ef4444);
}

.usage-metric__label {
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
  font-size: 10px;
}

.usage-metric__value {
  color: var(--color-text-primary);
  font-weight: 600;
  font-size: var(--text-sm);
}

.usage-chart__svg-wrap {
  position: relative;
  background: linear-gradient(
    180deg,
    rgba(139, 92, 246, 0.04),
    rgba(245, 158, 11, 0.02)
  );
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 8px 0 0;
  overflow: hidden;
}

.usage-chart__svg {
  display: block;
  width: 100%;
  height: 220px;
}

.usage-chart__grid line {
  stroke: var(--color-border);
  stroke-dasharray: 3 4;
  stroke-width: 1;
  opacity: 0.5;
}

.usage-chart__axis text {
  font-size: 10px;
  fill: var(--color-text-muted);
}

.usage-chart__xticks text {
  font-size: 10px;
  fill: var(--color-text-muted);
}

.usage-chart__area {
  opacity: 0.55;
  transition: opacity 0.15s ease;
}

.usage-chart__bars rect {
  transition: opacity 0.18s ease, transform 0.18s ease,
    filter 0.18s ease;
  transform-origin: center bottom;
  transform-box: fill-box;
  /* Cute bounce-in. */
  animation: bar-pop 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) backwards;
}

.usage-chart__bars rect:nth-child(2) { animation-delay: 0.02s; }
.usage-chart__bars rect:nth-child(3) { animation-delay: 0.03s; }
.usage-chart__bars rect:nth-child(4) { animation-delay: 0.04s; }
.usage-chart__bars rect:nth-child(5) { animation-delay: 0.05s; }
.usage-chart__bars rect:nth-child(6) { animation-delay: 0.06s; }
.usage-chart__bars rect:nth-child(7) { animation-delay: 0.07s; }
.usage-chart__bars rect:nth-child(8) { animation-delay: 0.08s; }
.usage-chart__bars rect:nth-child(9) { animation-delay: 0.09s; }
.usage-chart__bars rect:nth-child(10) { animation-delay: 0.10s; }

.usage-chart__bar--hover {
  filter: brightness(1.1) drop-shadow(0 2px 8px rgba(139, 92, 246, 0.35));
  transform: scaleY(1.03);
}

.usage-chart__bar--empty {
  opacity: 0.25;
}

.usage-chart__dots circle {
  opacity: 0;
  transition: opacity 0.15s ease, r 0.15s ease;
}

.usage-chart__dots circle.usage-chart__dot--hover {
  opacity: 1;
}

.usage-chart__dots circle.usage-chart__dot--hidden {
  opacity: 0 !important;
}

.usage-chart__guide {
  stroke: var(--color-text-muted);
  stroke-dasharray: 3 3;
  stroke-width: 1;
  opacity: 0.4;
}

/* Tooltip */
.usage-tooltip {
  position: absolute;
  bottom: calc(100% - 208px);
  top: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12),
    0 2px 6px rgba(15, 23, 42, 0.08);
  padding: 10px 12px;
  font-size: var(--text-xs);
  min-width: 200px;
  pointer-events: none;
  z-index: 5;
}

.usage-tooltip__title {
  margin: 0 0 6px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.usage-tooltip__grid {
  margin: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
}

.usage-tooltip__grid > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.usage-tooltip__grid dt {
  font-size: 10px;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.usage-tooltip__grid dd {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-primary);
  font-weight: 500;
}

.usage-chart__empty {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  text-align: center;
}

@keyframes bar-pop {
  0% {
    transform: scaleY(0);
    opacity: 0;
  }
  60% {
    transform: scaleY(1.06);
    opacity: 1;
  }
  100% {
    transform: scaleY(1);
    opacity: 1;
  }
}

@media (max-width: 640px) {
  .usage-chart__header {
    flex-direction: column;
    align-items: stretch;
  }
  .usage-chart__controls {
    align-self: flex-start;
  }
  .usage-chart__svg {
    height: 180px;
  }
}
</style>
