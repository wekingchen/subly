<template>
  <AppModal
    :model-value="true"
    :title="t('creditCards.detailTitle')"
    width="580px"
    :close-label="t('common.close')"
    @update:model-value="onModalChange"
    @close="$emit('close')"
  >
    <div class="detail-identity">
      <div class="detail-card" aria-hidden="true">
        <span class="detail-chip"></span>
        <CreditCardBrandBadge class="detail-brand" :bank-name="card.bank_name" />
        <strong>{{ card.display_name }}</strong>
        <span>{{ card.bank_name }}</span>
        <b v-if="card.last_four" class="mono-data">···· {{ card.last_four }}</b>
      </div>
      <div class="detail-status">
        <span class="tag">{{ card.is_active ? t('creditCards.active') : t('creditCards.inactive') }}</span>
        <span class="muted">{{ card.show_in_calendar ? t('creditCards.calendarOn') : t('creditCards.calendarOff') }}</span>
      </div>
    </div>

    <CreditCardCycleTrack :card="card" />

    <dl class="detail-grid">
      <div><dt>{{ t('creditCards.statementDay') }}</dt><dd>{{ t('creditCards.monthDayValue', { n: card.statement_day }) }}</dd></div>
      <div><dt>{{ t('creditCards.dueDay') }}</dt><dd>{{ t('creditCards.monthDayValue', { n: card.due_day }) }}</dd></div>
      <div><dt>{{ t('creditCards.remindDaysBefore') }}</dt><dd>{{ t('creditCards.remindValue', { n: card.remind_days_before }) }}</dd></div>
      <div><dt>{{ t('creditCards.repaymentWindow') }}</dt><dd>{{ card.statement_to_due_days != null ? t('creditCards.windowDays', { n: card.statement_to_due_days }) : '—' }}</dd></div>
      <div><dt>{{ t('creditCards.creditLimit') }}</dt><dd>{{ card.credit_limit != null ? formatLimit(card.credit_limit) : '—' }}</dd></div>
    </dl>

    <aside class="disclaimer" role="note">
      <strong>{{ t('creditCards.disclaimerTitle') }}</strong>
      <p>{{ t('creditCards.disclaimer') }}</p>
    </aside>

    <template #footer>
      <button type="button" class="btn ghost" @click="$emit('close')">{{ t('common.close') }}</button>
      <button type="button" class="btn" @click="$emit('edit', card)">{{ t('creditCards.edit') }}</button>
    </template>
  </AppModal>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import AppModal from '../AppModal.vue'
import CreditCardBrandBadge from './CreditCardBrandBadge.vue'
import CreditCardCycleTrack from './CreditCardCycleTrack.vue'

defineProps({ card: { type: Object, required: true } })
const emit = defineEmits(['close', 'edit'])
const { t } = useI18n()
function formatLimit(value) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value))
}

function onModalChange(value) {
  if (!value) emit('close')
}
</script>

<style scoped>
.detail-identity { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.detail-card { display: grid; width: min(260px, 100%); min-height: 146px; padding: 18px; border-radius: 18px; background: linear-gradient(145deg, color-mix(in srgb, var(--primary) 76%, #0b1020), color-mix(in srgb, var(--signal-cyan) 48%, var(--primary))); color: #fff; box-shadow: 0 14px 30px color-mix(in srgb, var(--primary) 24%, transparent); }
.detail-chip { width: 32px; height: 23px; border-radius: 6px; background: linear-gradient(135deg, rgba(255,255,255,.86), rgba(255,255,255,.42)); }
.detail-card strong { align-self: end; margin-top: 18px; font-size: 17px; overflow-wrap: anywhere; }
.detail-brand { position: absolute; top: 14px; right: 14px; width: 40px; height: 31px; border-radius: 9px; overflow: hidden; border: 1px solid rgba(255,255,255,.34); }
.detail-card { position: relative; }
.detail-card > span:not(.detail-chip) { font-size: 12px; opacity: .82; }
.detail-card b { justify-self: end; margin-top: 4px; letter-spacing: .06em; }
.detail-status { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; font-size: 12px; text-align: right; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 16px 0 0; }
.detail-grid div { min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
.detail-grid dt { color: var(--text-soft); font-size: 11px; }
.detail-grid dd { margin: 5px 0 0; font-size: 14px; font-weight: 750; overflow-wrap: anywhere; }
.disclaimer { margin-top: 16px; padding: 13px 14px; border: 1px solid color-mix(in srgb, var(--warning) 38%, var(--border)); border-radius: 12px; background: color-mix(in srgb, var(--warning) 7%, var(--surface)); }
.disclaimer strong { color: var(--warning-text); font-size: 12px; }
.disclaimer p { margin: 5px 0 0; color: var(--text-soft); font-size: 12px; line-height: 1.6; }
@media (max-width: 520px) {
  .detail-identity { align-items: stretch; flex-direction: column; }
  .detail-card { width: 100%; }
  .detail-status { align-items: flex-start; text-align: left; }
  .detail-grid { grid-template-columns: 1fr; }
}
</style>
