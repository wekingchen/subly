<template>
  <div class="trend">
    <div class="trend-head">
      <div class="trend-legend">
        <span class="lg-item"><span class="lg-dot hist"></span>{{ t('reports.trendHistory') }}</span>
        <span class="lg-item"><span class="lg-dot fut"></span>{{ t('reports.trendFuture') }}</span>
      </div>
      <div class="seg trend-view-switch" :aria-label="t('reports.trendView')">
        <button type="button" :class="{ on: view === 'chart' }" :aria-pressed="view === 'chart'" @click="view = 'chart'">{{ t('reports.trendChartView') }}</button>
        <button type="button" :class="{ on: view === 'table' }" :aria-pressed="view === 'table'" @click="view = 'table'">{{ t('reports.trendTableView') }}</button>
      </div>
    </div>

    <template v-if="bars.some((bar) => bar.total > 0)">
      <div v-if="view === 'chart'" class="trend-plot">
        <div class="axis-label max mono-data">{{ axisLabels.max }}</div>
        <div class="axis-label mid mono-data">{{ axisLabels.mid }}</div>
        <div class="axis-label zero mono-data">{{ axisLabels.zero }}</div>
        <div class="trend-scroll">
          <div class="trend-chart" :style="{ minWidth: `${Math.max(260, bars.length * 54)}px` }">
            <div v-for="(bar, index) in bars" :key="bar.key" class="trend-col">
              <div
                class="trend-bar-wrap"
                role="img"
                :tabindex="rovingIndex === index ? 0 : -1"
                :aria-label="bar.ariaLabel"
                :aria-describedby="tooltipIndex === index ? tooltipId : undefined"
                @focus="activate(index)"
                @blur="deactivateLater"
                @mouseenter="activate(index)"
                @mouseleave="deactivateLater"
                @click="toggle(index)"
                @keydown="onBarKeydown($event, index)"
              >
                <div v-if="tooltipIndex === index" :id="tooltipId" class="trend-tooltip" role="tooltip">
                  <strong>{{ bar.month }}</strong>
                  <span>{{ t('reports.trendHistory') }}：{{ bar.historyText }}</span>
                  <span>{{ t('reports.trendFuture') }}：{{ bar.futureText }}</span>
                  <span>{{ t('reports.total') }}：{{ bar.totalText }}</span>
                </div>
                <div class="trend-stack">
                  <div v-if="bar.futureHeight" class="trend-segment fut" :style="{ height: bar.futureHeight + '%' }"></div>
                  <div v-if="bar.historyHeight" class="trend-segment hist" :style="{ height: bar.historyHeight + '%' }"></div>
                </div>
              </div>
              <span class="trend-year">{{ bar.yearLabel }}</span>
              <span class="trend-month" :class="{ current: bar.current }">{{ bar.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="trend-table-wrap">
        <table>
          <thead><tr><th>{{ t('reports.trendMonth') }}</th><th>{{ t('reports.trendHistory') }}</th><th>{{ t('reports.trendFuture') }}</th><th>{{ t('reports.total') }}</th></tr></thead>
          <tbody>
            <tr v-for="bar in bars" :key="bar.key">
              <td class="mono-data">{{ bar.month }}</td><td>{{ bar.historyText }}</td><td>{{ bar.futureText }}</td><td>{{ bar.totalText }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <p v-else class="muted trend-empty">{{ t('reports.trendEmpty') }}</p>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatMoney } from '../utils/money'
import { buildTrendViewModel } from '../utils/trend'

const props = defineProps({
  history: { type: Array, default: () => [] },
  future: { type: Array, default: () => [] },
  baseCurrency: { type: String, default: 'CNY' },
  currentMonth: { type: String, default: '' }
})

const { t } = useI18n()
const view = ref('chart')
const rovingIndex = ref(0)
const tooltipIndex = ref(-1)
const tooltipId = 'reports-trend-tooltip'
let closeTimer = null
const bars = computed(() => buildTrendViewModel(props.history, props.future, {
  baseCurrency: props.baseCurrency,
  currentMonth: props.currentMonth
}))
const maxTotal = computed(() => Math.max(0, ...bars.value.map((bar) => bar.total)))
const axisLabels = computed(() => ({
  max: formatMoney(maxTotal.value, props.baseCurrency),
  mid: formatMoney(maxTotal.value / 2, props.baseCurrency),
  zero: formatMoney(0, props.baseCurrency)
}))

watch(() => bars.value.length, (length) => {
  rovingIndex.value = length ? Math.min(rovingIndex.value, length - 1) : 0
  if (tooltipIndex.value >= length) tooltipIndex.value = -1
})

function activate(index) {
  if (closeTimer) clearTimeout(closeTimer)
  rovingIndex.value = index
  tooltipIndex.value = index
}
function deactivateLater() {
  if (closeTimer) clearTimeout(closeTimer)
  closeTimer = setTimeout(() => { tooltipIndex.value = -1 }, 80)
}
function toggle(index) {
  rovingIndex.value = index
  tooltipIndex.value = tooltipIndex.value === index ? -1 : index
}
async function focusBar(index) {
  const next = Math.max(0, Math.min(index, bars.value.length - 1))
  rovingIndex.value = next
  tooltipIndex.value = next
  await nextTick()
  const elements = globalThis.document.querySelectorAll('.trend-bar-wrap')
  elements[next]?.focus()
  elements[next]?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
}
function onBarKeydown(event, index) {
  if (event.key === 'ArrowLeft') { event.preventDefault(); focusBar(index - 1) }
  else if (event.key === 'ArrowRight') { event.preventDefault(); focusBar(index + 1) }
  else if (event.key === 'Home') { event.preventDefault(); focusBar(0) }
  else if (event.key === 'End') { event.preventDefault(); focusBar(bars.value.length - 1) }
  else if (event.key === 'Escape') { event.preventDefault(); tooltipIndex.value = -1 }
}
</script>

<style scoped>
.trend { display: flex; flex-direction: column; gap: 10px; }
.trend-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.trend-legend { display: flex; gap: 14px; font-size: 12px; color: var(--text-soft); }
.lg-item { display: flex; align-items: center; gap: 5px; }
.lg-dot { width: 9px; height: 9px; border-radius: 3px; }
.lg-dot.hist { background: var(--primary); }
.lg-dot.fut { background: color-mix(in srgb, var(--primary) 30%, var(--border)); border: 1px dashed var(--primary); }
.trend-view-switch button { min-height: 36px; }
.trend-plot { position: relative; padding-left: 72px; }
.trend-scroll { max-width: 100%; overflow-x: auto; overscroll-behavior-inline: contain; border-bottom: 1px solid var(--border); }
.axis-label { position: absolute; left: 0; color: var(--text-soft); font-size: 11px; }
.axis-label.max { top: 8px; } .axis-label.mid { top: 50%; transform: translateY(-50%); } .axis-label.zero { bottom: 25px; }
.trend-chart { display: flex; align-items: flex-end; gap: 8px; height: 180px; padding: 8px 4px 0; }
.trend-col { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 2px; height: 100%; }
.trend-bar-wrap { position: relative; flex: 1 1 0; width: 100%; display: flex; align-items: flex-end; justify-content: center; min-height: 0; cursor: pointer; }
.trend-bar-wrap:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.trend-stack { width: 70%; max-width: 30px; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; }
.trend-segment { width: 100%; min-height: 2px; transition: height .4s ease; }
.trend-segment.hist { background: var(--primary); }
.trend-segment.fut { background: color-mix(in srgb, var(--primary) 30%, var(--border)); border: 1px dashed color-mix(in srgb, var(--primary) 70%, transparent); border-radius: 6px 6px 0 0; }
.trend-segment.hist:first-child { border-radius: 6px 6px 0 0; }
.trend-tooltip { position: absolute; z-index: 5; left: 50%; bottom: calc(100% + 8px); transform: translateX(-50%); display: grid; gap: 3px;
  min-width: 180px; padding: 9px 11px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); box-shadow: var(--shadow-lg);
  color: var(--text); font-size: 12px; pointer-events: none; }
.trend-year { min-height: 14px; color: var(--text-soft); font-size: 10px; }
.trend-month { font-size: 11px; color: var(--text-soft); }
.trend-month.current { color: var(--primary); font-weight: 700; }
.trend-table-wrap { overflow-x: auto; }
.trend-table-wrap table { min-width: 560px; }
.trend-empty { text-align: center; padding: 20px 0; }
@media (max-width: 720px) { .trend-plot { padding-left: 58px; } .trend-chart { height: 150px; } .trend-stack { max-width: 24px; } }
@media (prefers-reduced-motion: reduce) { .trend-segment { transition: none; } }
</style>
