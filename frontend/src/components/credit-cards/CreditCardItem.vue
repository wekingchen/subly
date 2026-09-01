<template>
  <article class="credit-card card" :class="{ inactive: !card.is_active, 'is-best': highlight }">
    <div class="card-head">
      <div class="card-glyph" aria-hidden="true">
        <CreditCardBrandBadge :bank-name="card.bank_name" />
      </div>
      <div class="card-title">
        <div class="card-name">{{ card.display_name }}</div>
        <div class="card-bank">{{ card.bank_name }}<template v-if="card.last_four"> ···· {{ card.last_four }}</template></div>
      </div>
      <span class="status-tag" :class="card.is_active ? 'active' : 'inactive-tag'">
        {{ card.is_active ? t('creditCards.active') : t('creditCards.inactive') }}
      </span>
    </div>

    <CreditCardCycleTrack :card="card" />

    <!-- 待还信息行：用户最关注的金额与逾期状态；名义日/提醒/额度等细节在详情 -->
    <div v-if="outstandingEntry" class="outstanding-line">
      <span class="outstanding-label">{{ t('creditCards.outstandingOfCard') }}</span>
      <span class="outstanding-amt mono-data" :class="{ 'is-overdue': outstandingEntry.max_overdue_days > 0 }">{{ formatLimit(outstandingEntry.total_due) }}</span>
      <span v-if="outstandingEntry.max_overdue_days > 0" class="overdue-tag">{{ t('creditCards.overdueDays', { n: outstandingEntry.max_overdue_days }) }}</span>
    </div>

    <div class="card-actions">
      <button
        v-if="outstandingEntry"
        type="button"
        class="btn ghost sm repay-btn"
        :disabled="disabled"
        :title="t('creditCards.markRepaidHint', { cycles: buildRepaidScopeText(outstandingEntry, t) })"
        @click="$emit('mark-repaid', card)"
      >
        <span aria-hidden="true">✓</span> {{ t('creditCards.markRepaid') }}
        <span class="repay-amt mono-data">{{ formatLimit(outstandingEntry.total_due) }}</span>
      </button>
      <button type="button" class="btn ghost sm" :disabled="disabled" @click="$emit('view', card)">{{ t('creditCards.viewDetails') }}</button>
      <button type="button" class="btn ghost sm" :disabled="disabled" @click="$emit('edit', card)">{{ t('creditCards.edit') }}</button>
      <button type="button" class="btn danger sm" :disabled="disabled" @click="$emit('delete', card)">{{ t('creditCards.delete') }}</button>
    </div>
  </article>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import CreditCardBrandBadge from './CreditCardBrandBadge.vue'
import CreditCardCycleTrack from './CreditCardCycleTrack.vue'
import { buildRepaidScopeText } from '../../utils/creditCardDates'

defineProps({
  card: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  highlight: { type: Boolean, default: false },
  // 该卡未标记还款的汇总 { total_due, count, cycles, overdue_cycles, max_overdue_days }；
  // 无未还账单为 null（待还行与按钮隐藏）
  outstandingEntry: { type: Object, default: null }
})

defineEmits(['view', 'edit', 'delete', 'mark-repaid'])
const { t } = useI18n()

// 额度仅作展示记录：千分位整数（有小数保留两位），不带币种符号——币种跟随用户基准币。
function formatLimit(value) {
  const n = Number(value)
  return Number.isInteger(n) ? n.toLocaleString('zh-CN') : n.toFixed(2)
}
</script>

<style scoped>
.credit-card { position: relative; display: flex; min-width: 0; flex-direction: column; gap: 14px; overflow: hidden; }
.credit-card::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 4px; background: linear-gradient(180deg, var(--signal-cyan), var(--primary)); }
.credit-card.inactive { opacity: .68; border-style: dashed; }
.credit-card.inactive::before { background: var(--text-soft); opacity: .5; }
.card-head { display: flex; min-width: 0; align-items: center; gap: 11px; }
.card-glyph { position: relative; display: flex; width: 44px; height: 34px; flex: 0 0 44px; align-items: stretch; padding: 0; border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border)); border-radius: 10px; overflow: hidden; box-shadow: 0 6px 16px color-mix(in srgb, var(--primary) 18%, transparent); }
.card-title { min-width: 0; flex: 1; }
.card-name { overflow: hidden; font-size: 16px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.card-bank { margin-top: 3px; color: var(--text-soft); font-size: 12px; overflow-wrap: anywhere; }
.status-tag { flex: 0 0 auto; padding: 4px 9px; border-radius: 999px; font-size: 11px; font-weight: 750; }
.status-tag.active { background: color-mix(in srgb, var(--success) 11%, var(--surface)); color: var(--success-text); }
.status-tag.inactive-tag { background: var(--surface-2); color: var(--text-soft); }
.outstanding-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; padding: 9px 12px; border: 1px solid color-mix(in srgb, var(--warning) 32%, var(--border)); border-radius: 10px; background: color-mix(in srgb, var(--warning) 6%, var(--surface)); }
.outstanding-line .is-overdue, .outstanding-line.is-overdue .outstanding-amt { color: var(--danger-text); }
.outstanding-label { color: var(--text-soft); font-size: 12px; font-weight: 750; }
.outstanding-amt { font-size: 18px; font-weight: 800; color: var(--warning-text); }
.overdue-tag { margin-left: auto; padding: 2px 8px; border-radius: 999px; background: color-mix(in srgb, var(--danger) 13%, transparent); color: var(--danger-text); font-size: 11px; font-weight: 750; }
.credit-card.is-best { border-color: color-mix(in srgb, var(--signal-cyan) 55%, var(--border)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--signal-cyan) 30%, transparent), 0 8px 22px color-mix(in srgb, var(--signal-cyan) 14%, transparent); }
.credit-card.is-best::before { background: linear-gradient(180deg, var(--signal-cyan), var(--primary)); box-shadow: 0 0 12px color-mix(in srgb, var(--signal-cyan) 55%, transparent); }
.card-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: auto; padding-top: 2px; }
.card-actions .btn { flex: 1 1 auto; }
.repay-btn { color: var(--success-text); border-color: color-mix(in srgb, var(--success) 38%, var(--border)); }
.repay-amt { margin-left: 4px; font-weight: 800; }
@media (hover: hover) and (pointer: fine) {
  .credit-card { transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease; }
  .credit-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
}
@media (max-width: 420px) {
  .card-head { align-items: flex-start; flex-wrap: wrap; }
  .card-title { flex-basis: calc(100% - 56px); }
  .status-tag { margin-left: 55px; }
  .card-name { white-space: normal; }
  .card-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .card-actions .btn:first-child { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) {
  .credit-card { transition: none; }
}
</style>
