<template>
  <div class="trend">
    <div class="trend-legend">
      <span class="lg-item"><span class="lg-dot hist"></span>{{ t('reports.trendHistory') }}</span>
      <span class="lg-item"><span class="lg-dot fut"></span>{{ t('reports.trendFuture') }}</span>
    </div>
    <div class="trend-chart" v-if="bars.length">
      <div v-for="b in bars" :key="b.key" class="trend-col">
        <div class="trend-bar-wrap" :title="b.tooltip">
          <div class="trend-stack">
            <div v-if="b.futH" class="trend-segment fut" :style="{ height: b.futH + '%' }"></div>
            <div v-if="b.histH" class="trend-segment hist" :style="{ height: b.histH + '%' }"></div>
          </div>
        </div>
        <span class="trend-month" :class="{ current: b.current }">{{ b.label }}</span>
      </div>
    </div>
    <p v-else class="muted trend-empty">{{ t('reports.trendEmpty') }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatMoney } from '../utils/money'

const props = defineProps({
  history: { type: Array, default: () => [] },      // [{month:'YYYY-MM', amount}]
  future: { type: Array, default: () => [] },        // [{month:'YYYY-MM', amount}]
  baseCurrency: { type: String, default: 'CNY' },
  currentMonth: { type: String, default: '' }        // 当前月 YYYY-MM（区分历史/未来分界）
})

const { t } = useI18n()

const bars = computed(() => {
  // 按月分别聚合历史与未来金额，避免合并后丢失来源（决定柱子颜色）。
  const byMonth = new Map()
  const ensure = (month) => {
    if (!byMonth.has(month)) byMonth.set(month, { month, hist: 0, fut: 0 })
    return byMonth.get(month)
  }
  for (const h of props.history) ensure(h.month).hist += h.amount || 0
  for (const f of props.future) ensure(f.month).fut += f.amount || 0

  const rows = [...byMonth.values()].sort((a, b) => a.month.localeCompare(b.month))
  // 用合并后的总额算 max，避免柱高超过 100%
  const max = Math.max(1, ...rows.map((r) => r.hist + r.fut))
  return rows.map((r) => {
    const total = r.hist + r.fut
    const details = []
    if (r.hist > 0) details.push(`${t('reports.trendHistory')}: ${formatMoney(r.hist, props.baseCurrency)}`)
    if (r.fut > 0) details.push(`${t('reports.trendFuture')}: ${formatMoney(r.fut, props.baseCurrency)}`)
    return {
      key: r.month,
      label: r.month.slice(5),
      current: r.month === props.currentMonth,
      histH: r.hist > 0 ? (r.hist / max) * 100 : 0,
      futH: r.fut > 0 ? (r.fut / max) * 100 : 0,
      tooltip: `${r.month}\n${details.join('\n')}\n${t('reports.total')}: ${formatMoney(total, props.baseCurrency)}`
    }
  })
})
</script>

<style scoped>
.trend { display: flex; flex-direction: column; gap: 10px; }
.trend-legend { display: flex; gap: 14px; font-size: 12px; color: var(--text-soft); }
.lg-item { display: flex; align-items: center; gap: 5px; }
.lg-dot { width: 9px; height: 9px; border-radius: 3px; }
.lg-dot.hist { background: var(--primary); }
.lg-dot.fut { background: color-mix(in srgb, var(--primary) 30%, var(--border)); }
.trend-chart { display: flex; align-items: flex-end; gap: 6px; height: 140px; padding: 8px 4px 0; }
.trend-col { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 4px; height: 100%; }
.trend-bar-wrap { flex: 1 1 0; width: 100%; display: flex; align-items: flex-end; justify-content: center; min-height: 0; }
.trend-stack { width: 70%; max-width: 28px; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; }
.trend-segment { width: 100%; min-height: 2px; transition: height .4s ease; }
.trend-segment.hist { background: var(--primary); }
.trend-segment.fut { background: color-mix(in srgb, var(--primary) 30%, var(--border)); border: 1px dashed color-mix(in srgb, var(--primary) 50%, transparent); border-radius: 6px 6px 0 0; }
.trend-segment.hist:first-child { border-radius: 6px 6px 0 0; }
.trend-month { font-size: 11px; color: var(--text-soft); }
.trend-month.current { color: var(--primary); font-weight: 700; }
.trend-empty { text-align: center; padding: 20px 0; }
@media (max-width: 720px) { .trend-chart { height: 110px; } .trend-stack { max-width: 20px; } }
@media (prefers-reduced-motion: reduce) { .trend-segment { transition: none; } }
</style>
