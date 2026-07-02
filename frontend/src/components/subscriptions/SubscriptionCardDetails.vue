<template>
  <Transition name="detail">
    <div v-if="expanded" :id="detailId" class="sc-detail" @click.stop>
      <div class="detail-section">
        <div class="detail-title">{{ t('sub.detailIdentityCost') }}</div>
        <div class="detail-grid">
          <div class="detail-item"><div class="detail-label">{{ t('sub.category') }}</div><div class="detail-value">{{ categoryName }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.plan') }}</div><div class="detail-value">{{ textOrDash(subscription?.plan) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.originalAmount') }}</div><div class="detail-value mono-data"><MoneyText :value="subscription?.amount" :currency="subscription?.currency" position="suffix" /></div></div>
          <div v-if="showBaseAmount" class="detail-item"><div class="detail-label">{{ t('sub.baseCurrencyAmount') }} · {{ baseCurrency }}</div><div class="detail-value mono-data"><MoneyText :value="baseAmount" :currency="baseCurrency" position="suffix" muted /></div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.billingType') }}</div><div class="detail-value">{{ subscription?.billing_type === 'one_time' ? t('sub.oneTime') : t('sub.recurring') }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.cycle') }}</div><div class="detail-value">{{ subscription?.billing_type === 'recurring' ? cycleText : DASH }}</div></div>
          <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.website') }}</div><div class="detail-value"><a v-if="subscription?.url" :href="subscription.url" target="_blank" rel="noopener noreferrer" @click.stop>{{ subscription.url }}</a><span v-else>{{ DASH }}</span></div></div>
          <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.remark') }}</div><div class="detail-value">{{ textOrDash(subscription?.remark) }}</div></div>
        </div>
      </div>

      <div class="detail-section">
        <div class="detail-title">{{ t('sub.detailRiskReminder') }}</div>
        <div class="detail-grid">
          <div class="detail-item"><div class="detail-label">{{ t('sub.startDate') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.start_date) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.nextRenewal') }}</div><div class="detail-value mono-data">{{ subscription?.billing_type === 'recurring' ? textOrDash(subscription?.next_renewal_date) : t('sub.lifetime') }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.endDate') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.end_date) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.lastRenewedAt') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.last_renewed_at) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.remindDays') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.remind_days_before) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.autoRenew') }}</div><div class="detail-value">{{ boolText(subscription?.auto_renew) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.calendarVisible') }}</div><div class="detail-value">{{ boolText(subscription?.show_in_calendar) }}</div></div>
        </div>
      </div>

      <div class="detail-section">
        <div class="detail-title">{{ t('sub.detailAccountingOwner') }}</div>
        <div class="detail-grid">
          <div class="detail-item"><div class="detail-label">{{ t('sub.payment') }}</div><div class="detail-value">{{ paymentName || DASH }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.bundle') }}</div><div class="detail-value">{{ bundleName || DASH }}</div></div>
          <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.family') }}</div><div class="detail-value">{{ familyText }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.ipv4') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.ipv4) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.ipv6') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.ipv6) }}</div></div>
          <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.notes') }}</div><div class="detail-value">{{ textOrDash(subscription?.notes) }}</div></div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import MoneyText from '../MoneyText.vue'

const DASH = '—'

defineProps({
  subscription: { type: Object, required: true },
  expanded: { type: Boolean, default: false },
  detailId: { type: String, required: true },
  categoryName: { type: String, default: '' },
  baseCurrency: { type: String, default: 'CNY' },
  baseAmount: { type: [Number, String], default: 0 },
  showBaseAmount: { type: Boolean, default: false },
  cycleText: { type: String, default: '' },
  paymentName: { type: String, default: '' },
  bundleName: { type: String, default: '' },
  familyText: { type: String, default: DASH }
})

const { t } = useI18n()
function textOrDash(v) { return (v === null || v === undefined || v === '') ? DASH : v }
function boolText(v) { return v ? '✓' : '✗' }
</script>

<style scoped>
.sc-detail { margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--border); display: grid; gap: 12px; }
.detail-section { border: 1px solid var(--border); border-radius: 14px; padding: 12px;
  background: color-mix(in srgb, var(--surface-2) 76%, transparent); }
.detail-title { font-size: 13px; font-weight: 850; color: var(--primary); margin-bottom: 9px; letter-spacing: -.01em; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px 12px; }
.detail-item { min-width: 0; }
.detail-item--full { grid-column: 1 / -1; }
.detail-label { font-size: 11px; color: var(--text-soft); margin-bottom: 2px; }
.detail-value { font-size: 13px; line-height: 1.45; word-break: break-word; }
.detail-value a { color: var(--primary); text-decoration: none; }
.detail-value a:hover { text-decoration: underline; }
.detail-enter-active, .detail-leave-active { transition: opacity .16s ease, transform .16s ease; }
.detail-enter-from, .detail-leave-to { opacity: 0; transform: translateY(-4px); }
@media (max-width: 720px) {
  .detail-section { padding: 10px; }
  .detail-grid { grid-template-columns: 1fr; }
  .detail-value { overflow-wrap: anywhere; }
}
</style>
