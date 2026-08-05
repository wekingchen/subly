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
          <div class="detail-item"><div class="detail-label">{{ t('sub.billingType') }}</div><div class="detail-value">{{ subscription?.billing_type === 'one_time' ? t('sub.oneTime') : (subscription?.is_keepalive ? t('sub.keepalive.label') : t('sub.recurring')) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.cycle') }}</div><div class="detail-value">{{ subscription?.billing_type === 'recurring' ? cycleText : DASH }}</div></div>
          <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.website') }}</div><div class="detail-value"><a v-if="subscription?.url" :href="subscription.url" target="_blank" rel="noopener noreferrer" @click.stop>{{ subscription.url }}</a><span v-else>{{ DASH }}</span></div></div>
          <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.remark') }}</div><div class="detail-value">{{ textOrDash(subscription?.remark) }}</div></div>
        </div>
      </div>

      <div class="detail-section">
        <div class="detail-title">{{ t('sub.detailRiskReminder') }}</div>
        <div class="detail-grid">
          <div class="detail-item"><div class="detail-label">{{ t('sub.startDate') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.start_date) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ subscription?.is_keepalive ? t('sub.keepalive.nextRenewal') : t('sub.nextRenewal') }}</div><div class="detail-value mono-data">{{ subscription?.billing_type === 'recurring' ? textOrDash(subscription?.next_renewal_date) : t('sub.lifetime') }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.endDate') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.end_date) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ subscription?.is_keepalive ? t('sub.keepalive.lastRenewedAt') : t('sub.lastRenewedAt') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.last_renewed_at) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.remindDays') }}</div><div class="detail-value mono-data">{{ textOrDash(subscription?.remind_days_before) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.autoRenew') }}</div><div class="detail-value">{{ boolText(subscription?.auto_renew) }}</div></div>
          <div class="detail-item"><div class="detail-label">{{ t('sub.calendarVisible') }}</div><div class="detail-value">{{ boolText(subscription?.show_in_calendar) }}</div></div>
          <div class="detail-item" v-if="subscription?.is_paused"><div class="detail-label">{{ t('sub.pausedLabel') }}</div><div class="detail-value">{{ t('sub.pausedHint') }}</div></div>
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

      <div v-if="subscription?.billing_type === 'recurring'" class="detail-section">
        <button type="button" class="rh-toggle" :aria-expanded="showRenewals"
                @click="showRenewals = !showRenewals">
          <span class="detail-title">{{ t('sub.renewalHistory') }}</span>
          <span class="rh-count mono-data" v-if="renewals.length">{{ renewals.length }}</span>
          <span class="rh-chev" :class="{ open: showRenewals }">›</span>
        </button>
        <div v-if="showRenewals" class="rh-list">
          <p v-if="!renewals.length" class="muted rh-empty">{{ t('sub.renewalHistoryEmpty') }}</p>
          <div v-for="(r, i) in renewals" :key="i" class="rh-row">
            <span class="rh-date mono-data">{{ r.renewed_at }}</span>
            <span class="rh-mode">{{ modeText(r.mode) }}</span>
            <span class="rh-amt mono-data"><MoneyText :value="r.amount" :currency="r.currency" position="suffix" muted /></span>
            <span class="rh-due mono-data">{{ r.prev_renewal_date || DASH }} → {{ r.next_renewal_date || DASH }}</span>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import MoneyText from '../MoneyText.vue'

const DASH = '—'

const props = defineProps({
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
  familyText: { type: String, default: '—' }
})

const { t } = useI18n()
function textOrDash(v) {
  if (v === null || v === undefined) return DASH
  if (typeof v === 'string') return v.trim() || DASH
  return v
}
function boolText(v) { return v ? '✓' : '✗' }

// 续费历史：仅周期订阅有；详情展开时按订阅 id 拉取，避免账本每张卡片预请求。
// watch 依赖 expanded（仅展开时拉）+ id（切换订阅）+ last_renewed_at（续费后同 id 也刷新）。
const renewals = ref([])
const showRenewals = ref(false)
async function loadRenewals(id) {
  if (!id) { renewals.value = []; return }
  try {
    const { data } = await api.get(`/api/subscriptions/${id}/renewals`)
    renewals.value = Array.isArray(data) ? data : []
  } catch {
    renewals.value = []
  }
}
watch(
  () => [props.expanded, props.subscription?.id, props.subscription?.last_renewed_at],
  ([expanded, id]) => {
    if (expanded && props.subscription?.billing_type === 'recurring') loadRenewals(id)
    else if (!expanded) renewals.value = []  // 收起时清空，避免旧数据残留
  },
  { immediate: true }
)
function modeText(mode) {
  if (mode === 'due') return t('sub.renewModeDueShort')
  return t('sub.renewModeTodayShort')
}
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

/* 续费历史：折叠区块，避免详情默认过长 */
.rh-toggle { display: flex; align-items: center; gap: 8px; width: 100%; padding: 0;
  background: transparent; border: none; cursor: pointer; text-align: left; }
.rh-toggle .detail-title { margin-bottom: 0; }
.rh-count { background: var(--surface); color: var(--text-soft); border: 1px solid var(--border);
  border-radius: 999px; padding: 1px 8px; font-size: 11px; }
.rh-chev { margin-left: auto; color: var(--text-soft); transition: transform .15s ease; font-size: 16px; }
.rh-chev.open { transform: rotate(90deg); }
.rh-list { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.rh-empty { margin: 0; font-size: 12px; }
.rh-row { display: grid; grid-template-columns: auto auto 1fr; align-items: center; gap: 6px 10px;
  font-size: 12px; padding: 6px 8px; border-radius: 8px; background: var(--surface);
  border: 1px solid var(--border); }
.rh-date { color: var(--text); font-weight: 600; }
.rh-mode { font-size: 11px; color: var(--primary); background: color-mix(in srgb, var(--primary) 10%, transparent);
  border-radius: 999px; padding: 1px 7px; white-space: nowrap; }
.rh-amt { color: var(--text-soft); white-space: nowrap; }
.rh-due { grid-column: 1 / -1; color: var(--text-soft); font-size: 11px; }
.detail-enter-active, .detail-leave-active { transition: opacity .16s ease, transform .16s ease; }
.detail-enter-from, .detail-leave-to { opacity: 0; transform: translateY(-4px); }
@media (max-width: 720px) {
  .detail-section { padding: 10px; }
  .detail-grid { grid-template-columns: 1fr; }
  .detail-value { overflow-wrap: anywhere; }
}
</style>
