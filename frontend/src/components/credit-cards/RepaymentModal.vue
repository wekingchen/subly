<template>
  <AppModal
    :model-value="true"
    :title="t('creditCards.repayTitle')"
    width="430px"
    :close-label="t('common.close')"
    :pending="pending"
    @close="$emit('close')"
  >
    <form id="repay-form" @submit.prevent="submit">
      <p class="repay-scope muted">{{ target.cyclesText }}</p>
      <div class="repay-summary">
        <span class="repay-label">{{ t('creditCards.repayRemaining', { amount: formatAmount(target.remaining) }) }}</span>
        <span v-if="target.repaidAmount > 0" class="repaid-so-far">
          {{ t('creditCards.repaidSoFar', { amount: formatAmount(target.repaidAmount) }) }}
        </span>
      </div>

      <div class="field">
        <label for="repay-amount">{{ t('creditCards.repayAmountLabel') }}</label>
        <!-- type="text" + inputmode="decimal"：number 会放行 e/-，非法态难控；
             默认填剩余全额（一次还清直接确认），用户主动点入时才清空——
             不给输入框设置自动聚焦（弹窗一打开就聚焦会立即触发清空，默认全额就没了）-->
        <input
          id="repay-amount"
          ref="amountRef"
          v-model="amount"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          :placeholder="t('creditCards.repayAmountPlaceholder', { amount: formatAmount(target.remaining) })"
          :aria-invalid="!!error"
          @focus="onFocus"
        />
        <span class="field-hint">{{ t('creditCards.repayRemaining', { amount: formatAmount(target.remaining) }) }}</span>
      </div>

      <p v-if="errorText" class="form-error" role="alert">{{ errorText }}</p>
      <p v-if="serverError" class="form-error" role="alert">{{ serverError }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn ghost" :disabled="pending" @click="$emit('close')">{{ t('creditCards.cancel') }}</button>
      <button type="submit" form="repay-form" class="btn" :disabled="pending">
        {{ pending ? t('common.processing') : t('creditCards.repayConfirm') }}
      </button>
    </template>
  </AppModal>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import AppModal from '../AppModal.vue'
import { formatAmountInput, nextAmountOnFocus, parseRepayAmount } from '../../utils/creditCardRepayment'

const props = defineProps({
  // 还款目标：{ kind: 'card'|'statement', name, remaining, repaidAmount, cyclesText }
  target: { type: Object, required: true },
  pending: { type: Boolean, default: false },
  // 服务端错误（明细入口无 toast——失败原因必须显示在弹窗内，审核 Medium 5）
  serverError: { type: String, default: '' }
})
const emit = defineEmits(['close', 'confirm'])

const { t } = useI18n()
// 默认值 = 剩余待还裸数字（无千分位——逗号会破坏解析）
const defaultValue = formatAmountInput(props.target.remaining)
const amount = ref(defaultValue)
const error = ref(null)
const amountRef = ref(null)

const errorText = computed(() => {
  if (error.value === 'invalid') return t('creditCards.repayAmountInvalid')
  if (error.value === 'exceeds') {
    return t('creditCards.repayAmountExceeds', { amount: formatAmount(props.target.remaining) })
  }
  return ''
})

// 卡片/明细金额格式：千分位整数或两位小数，不带货币符号（币种跟随基准币）
function formatAmount(value) {
  const n = Number(value)
  return Number.isInteger(n) ? n.toLocaleString('zh-CN') : n.toFixed(2)
}

function onFocus(event) {
  // 程序化聚焦（弹窗自动首焦等）不清空——只有用户真实手势（点击/Tab，
  // isTrusted=true）才执行「点中清空」，否则弹窗打开即默认金额被自动首焦
  // 清掉，直接点确认会因金额为空而不提交（e2e CI 实测根因）
  if (!event.isTrusted) return
  // 值仍是未改动的默认值 → 清空（用户要求的「点中清空」）；
  // 已有用户输入 → select() 全选，不销毁
  amount.value = nextAmountOnFocus(amount.value, defaultValue, () => amountRef.value?.select())
}

function submit() {
  const parsed = parseRepayAmount(amount.value, props.target.remaining)
  if (!parsed.ok) {
    error.value = parsed.error
    return
  }
  error.value = null
  emit('confirm', parsed.value)
}
</script>

<style scoped>
.repay-scope { margin: 0 0 10px; font-size: 12px; }
.repay-summary { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.repay-label { font-weight: 750; }
.repaid-so-far { font-size: 12px; color: var(--muted-text); }
.field { margin-bottom: 12px; }
.field label { display: block; margin-bottom: 4px; font-size: 13px; }
.field input { width: 100%; }
.field-hint { display: block; margin-top: 4px; font-size: 12px; color: var(--muted-text); }
.form-error { margin: 8px 0 0; font-size: 12px; color: var(--danger-text); }
.muted { color: var(--muted-text); }
</style>
