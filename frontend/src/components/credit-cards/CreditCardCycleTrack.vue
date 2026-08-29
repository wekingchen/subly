<template>
  <figure class="cycle" :class="`is-${cycle.phase}`" :aria-label="ariaLabel">
    <div class="cycle-head">
      <figcaption>{{ t('creditCards.cycleTitle') }}</figcaption>
      <span class="cycle-phase">{{ phaseLabel }}</span>
    </div>
    <div class="cycle-track" aria-hidden="true">
      <span class="cycle-fill" :style="{ width: `${cycle.progress}%` }"></span>
      <span class="cycle-point statement"></span>
      <span class="cycle-point due"></span>
      <span v-if="cycle.valid" class="cycle-today" :style="{ left: `${cycle.progress}%` }"></span>
    </div>
    <div class="cycle-labels">
      <div>
        <span>{{ t('creditCards.statementDate') }}</span>
        <strong class="mono-data">{{ formatCreditCardDate(cycle.statementDate) }}</strong>
      </div>
      <div class="cycle-span">
        <span v-if="cycle.spanDays != null">{{ t('creditCards.windowDays', { n: cycle.spanDays }) }}</span>
        <span v-else>{{ t('creditCards.datePending') }}</span>
      </div>
      <div class="align-right">
        <span>{{ t('creditCards.plannedDueDate') }}</span>
        <strong class="mono-data">{{ formatCreditCardDate(cycle.dueDate) }}</strong>
      </div>
    </div>
  </figure>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { creditCardCycle, formatCreditCardDate } from '../../utils/creditCardDates'

const props = defineProps({
  card: { type: Object, required: true },
  today: { type: [String, Date], default: () => new Date() }
})

const { t } = useI18n()
const cycle = computed(() => creditCardCycle(props.card, props.today))
const phaseLabel = computed(() => t(`creditCards.phase.${cycle.value.phase}`))
const ariaLabel = computed(() => {
  if (!cycle.value.valid) return t('creditCards.cycleUnavailable')
  return t('creditCards.cycleAria', {
    statement: formatCreditCardDate(cycle.value.statementDate),
    due: formatCreditCardDate(cycle.value.dueDate),
    days: cycle.value.spanDays,
    phase: phaseLabel.value
  })
})
</script>

<style scoped>
.cycle { min-width: 0; margin: 0; padding: 14px; border: 1px solid var(--border); border-radius: 14px;
  background: color-mix(in srgb, var(--surface-2) 72%, transparent); }
.cycle-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
.cycle figcaption { font-size: 12px; font-weight: 800; letter-spacing: .08em; color: var(--text-soft); }
.cycle-phase { flex: 0 0 auto; padding: 3px 8px; border-radius: 999px; background: var(--primary-soft); color: var(--primary); font-size: 11px; font-weight: 750; }
.cycle.is-overdue .cycle-phase { background: color-mix(in srgb, var(--danger) 12%, var(--surface)); color: var(--danger-text); }
.cycle-track { position: relative; height: 6px; margin: 0 7px; border-radius: 999px; background: color-mix(in srgb, var(--border) 72%, var(--surface)); }
.cycle-fill { position: absolute; inset: 0 auto 0 0; border-radius: inherit; background: linear-gradient(90deg, var(--signal-cyan), var(--primary)); transition: width .45s cubic-bezier(.2,.8,.2,1); }
.is-overdue .cycle-fill { background: var(--danger); }
.cycle-point { position: absolute; top: 50%; width: 12px; height: 12px; border: 2px solid var(--surface); border-radius: 999px; transform: translate(-50%, -50%); background: var(--signal-cyan); box-shadow: 0 0 0 1px color-mix(in srgb, var(--signal-cyan) 60%, var(--border)); }
.cycle-point.statement { left: 0; }
.cycle-point.due { left: 100%; background: var(--primary); box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary) 60%, var(--border)); }
.is-overdue .cycle-point.due { background: var(--danger); }
.cycle-today { position: absolute; top: 50%; width: 2px; height: 20px; border-radius: 999px; transform: translate(-50%, -50%); background: var(--text); box-shadow: 0 0 0 3px var(--surface); transition: left .45s cubic-bezier(.2,.8,.2,1); }
.cycle-labels { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 8px; margin-top: 12px; }
.cycle-labels > div { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.cycle-labels span { color: var(--text-soft); font-size: 11px; }
.cycle-labels strong { font-size: 12px; overflow-wrap: anywhere; }
.cycle-span { justify-content: flex-end; text-align: center; }
.align-right { align-items: flex-end; text-align: right; }
@media (max-width: 420px) {
  .cycle { padding: 12px; }
  .cycle-labels { grid-template-columns: 1fr 1fr; }
  .cycle-span { grid-column: 1 / -1; grid-row: 2; align-items: center; }
}
@media (prefers-reduced-motion: reduce) {
  .cycle-fill, .cycle-today { transition: none; }
}
</style>
