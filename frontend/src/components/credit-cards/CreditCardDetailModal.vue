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

    <CreditCardStatementList :card-id="card.id" @repaid-changed="(updated) => $emit('statements-changed', updated)" />

    <!-- 免年费进度（派生状态，详情懒加载现算；未配置不渲染）。
         加载失败必须响亮：区块消失会被误读成「未配置」——给错误态与重试 -->
    <section v-if="feeWaiver || feeWaiverError" class="fee-waiver" aria-label="免年费进度">
      <template v-if="feeWaiverError">
        <p class="fee-missing" role="alert">{{ t('creditCards.annualFeeLoadFailed') }}
          <button type="button" class="fee-retry" :disabled="feeWaiverLoading" @click="loadFeeWaiver">{{ t('imap.retry') }}</button>
        </p>
      </template>
      <template v-else-if="feeWaiver">
        <header class="fee-head">
          <strong>{{ t('creditCards.annualFeeTitle') }}</strong>
          <span v-if="feeWaiver.met" class="fee-met-tag">{{ t('creditCards.annualFeeMet') }}</span>
        </header>
        <p class="fee-window muted">{{ feeWaiver.window_start }} ~ {{ feeWaiver.window_end }}</p>
        <div class="fee-bar" role="img" :aria-label="feeBarLabel">
          <div class="fee-bar-fill" :class="{ met: feeWaiver.met }" :style="{ width: feeBarPct + '%' }"></div>
        </div>
        <p class="fee-progress">
          <template v-if="feeWaiver.target_count != null">{{ t('creditCards.annualFeeCountProgress', { n: feeWaiver.qualified_count, total: feeWaiver.target_count }) }}</template>
          <template v-if="feeWaiver.target_count != null && feeWaiver.target_amount != null"> · </template>
          <template v-if="feeWaiver.target_amount != null">
            <MoneyText :value="feeWaiver.qualified_amount" currency="CNY" position="prefix" /> / {{ formatLimit(feeWaiver.target_amount) }}
          </template>
        </p>
        <p v-if="feeWaiver.annual_fee_charged" class="fee-charged" role="alert">
          {{ t('creditCards.annualFeeCharged', {
            amount: formatLimit(feeWaiver.annual_fee_charged.amount),
            cycle: feeWaiver.annual_fee_charged.cycle || ''
          }) }}
        </p>
        <p v-if="feeWaiver.missing_cycles.length" class="fee-missing">
          {{ t('creditCards.annualFeeMissing', { n: feeWaiver.missing_cycles.length, cycles: feeWaiver.missing_cycles.join('、') }) }}
        </p>
      </template>
    </section>

    <dl class="detail-grid">
      <div><dt>{{ t('creditCards.statementDay') }}</dt><dd>{{ t('creditCards.monthDayValue', { n: card.statement_day }) }}</dd></div>
      <div><dt>{{ t('creditCards.dueDay') }}</dt><dd>{{ t('creditCards.monthDayValue', { n: card.due_day }) }}</dd></div>
      <div><dt>{{ t('creditCards.remindDaysBefore') }}</dt><dd>{{ t('creditCards.remindValue', { n: card.remind_days_before }) }}</dd></div>
      <div><dt>{{ t('creditCards.repaymentWindow') }}</dt><dd>{{ card.statement_to_due_days != null ? t('creditCards.windowDays', { n: card.statement_to_due_days }) : '—' }}</dd></div>
      <div><dt>{{ t('creditCards.interestFreeTitle') }}</dt><dd>{{ card.interest_free_days != null ? t('creditCards.interestFreeDays', { n: card.interest_free_days }) : '—' }}</dd></div>
      <div><dt>{{ t('creditCards.creditLimit') }}</dt><dd>{{ card.credit_limit != null ? formatLimit(card.credit_limit) : '—' }}</dd></div>
    </dl>

    <aside class="disclaimer" role="note">
      <strong>{{ t('creditCards.disclaimerTitle') }}</strong>
      <p>{{ t('creditCards.disclaimer') }}</p>
    </aside>

    <template #footer>
      <button type="button" class="btn ghost" @click="$emit('close')">{{ t('common.close') }}</button>
      <!-- 删除收进详情与卡片「⋯」：危险操作不在卡片主区直接暴露 -->
      <button type="button" class="btn ghost detail-delete" @click="$emit('delete', card)">{{ t('creditCards.delete') }}</button>
      <button type="button" class="btn" @click="$emit('edit', card)">{{ t('creditCards.edit') }}</button>
    </template>
  </AppModal>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import AppModal from '../AppModal.vue'
import MoneyText from '../MoneyText.vue'
import CreditCardBrandBadge from './CreditCardBrandBadge.vue'
import CreditCardCycleTrack from './CreditCardCycleTrack.vue'
import CreditCardStatementList from './CreditCardStatementList.vue'

const props = defineProps({ card: { type: Object, required: true } })
const emit = defineEmits(['close', 'edit', 'delete', 'statements-changed'])
const { t } = useI18n()
function formatLimit(value) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value))
}

// 免年费进度：配置了核卡日+目标的卡才请求；派生值随最新账单现算。
// watch immediate 即完成首次加载（onMounted 会重复请求一次，不加）；
// 加载失败置错误态展示重试——区块消失会被误读成「未配置」。
const feeWaiver = ref(null)
const feeWaiverError = ref(false)
const feeWaiverLoading = ref(false)
let feeSeq = 0
async function loadFeeWaiver() {
  if (!props.card?.fee_waiver_anchor_date) {
    feeWaiver.value = null
    feeWaiverError.value = false
    return
  }
  const seq = ++feeSeq
  feeWaiverLoading.value = true
  try {
    const { data } = await api.get(`/api/credit-cards/${props.card.id}/annual-fee`)
    if (seq !== feeSeq) return
    feeWaiver.value = data?.enabled ? data : null
    feeWaiverError.value = false
  } catch {
    if (seq !== feeSeq) return
    feeWaiverError.value = true // 响亮：明确错误+重试，不伪装成未配置
  } finally {
    if (seq === feeSeq) feeWaiverLoading.value = false
  }
}
watch(() => [props.card?.id, props.card?.fee_waiver_anchor_date], loadFeeWaiver, { immediate: true })
onBeforeUnmount(() => { feeSeq += 1 })

const feeBarPct = computed(() => {
  const f = feeWaiver.value
  if (!f) return 0
  const pcts = []
  // 退款可把金额打成负数：比例钳在 [0, 100]，负值按 0 处理
  if (f.target_count != null && f.target_count > 0) pcts.push(Math.min(100, Math.max(0, (f.qualified_count / f.target_count) * 100)))
  if (f.target_amount != null && f.target_amount > 0) pcts.push(Math.min(100, Math.max(0, (f.qualified_amount / f.target_amount) * 100)))
  return pcts.length ? Math.round(Math.max(...pcts)) : 0
})
const feeBarLabel = computed(() => {
  const f = feeWaiver.value
  if (!f) return ''
  return f.met ? t('creditCards.annualFeeMet') : t('creditCards.annualFeeBarLabel', { pct: feeBarPct.value })
})

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

/* 免年费进度区块：进度条 + 达标徽标；配色与页面信号色一致 */
.fee-waiver { margin-top: 16px; padding: 13px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
.fee-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.fee-met-tag { padding: 2px 9px; border-radius: 999px; background: color-mix(in srgb, var(--success) 13%, transparent); color: var(--success-text); font-size: 11px; font-weight: 750; }
.fee-window { margin: 4px 0 8px; font-size: 12px; }
.fee-bar { height: 8px; border-radius: 999px; background: color-mix(in srgb, var(--border) 70%, transparent); overflow: hidden; }
.fee-bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--primary), var(--primary-2)); transition: width .3s ease; }
.fee-bar-fill.met { background: linear-gradient(90deg, var(--success), color-mix(in srgb, var(--success) 70%, var(--primary))); }
.fee-progress { margin: 8px 0 0; font-size: 13px; font-weight: 650; }
.fee-charged { margin: 8px 0 0; color: var(--danger-text); font-size: 12px; font-weight: 650; }
.fee-missing { margin: 8px 0 0; color: var(--warning-text); font-size: 12px; }
.fee-retry { margin-left: 6px; padding: 0; border: 0; background: none; color: var(--primary); font: inherit; font-weight: 750; cursor: pointer; text-decoration: underline; }
.detail-delete { color: var(--danger-text); border-color: color-mix(in srgb, var(--danger) 38%, var(--border)); }
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
