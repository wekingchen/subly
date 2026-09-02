<template>
  <AppModal
    :model-value="true"
    :title="card ? t('creditCards.editTitle') : t('creditCards.addTitle')"
    width="620px"
    :close-label="t('common.close')"
    :pending="pending"
    initial-focus="#credit-card-display-name"
    @update:model-value="onModalChange"
    @close="$emit('close')"
  >
    <form id="credit-card-form" @submit.prevent="submit">
      <div class="form-grid">
        <div class="field field-wide">
          <label for="credit-card-display-name">{{ t('creditCards.displayName') }}</label>
          <input id="credit-card-display-name" v-model="form.display_name" required maxlength="64" autocomplete="off" :aria-invalid="!!error" />
        </div>
        <div class="field">
          <label for="credit-card-bank-name">{{ t('creditCards.bankName') }}</label>
          <input id="credit-card-bank-name" v-model="form.bank_name" required maxlength="64" autocomplete="organization" :aria-invalid="!!error" />
        </div>
        <div class="field">
          <label for="credit-card-last-four">{{ t('creditCards.lastFour') }}</label>
          <input id="credit-card-last-four" v-model="form.last_four" :maxlength="isEditing ? 4 : 64" inputmode="numeric" autocomplete="off" :placeholder="t('creditCards.lastFourPlaceholder')" :aria-invalid="!!error" />
          <span class="field-hint">{{ isEditing ? t('creditCards.lastFourHint') : t('creditCards.lastFourBatchHint') }}</span>
        </div>
        <div class="field">
          <label for="credit-card-statement-day">{{ t('creditCards.statementDay') }}</label>
          <input id="credit-card-statement-day" v-model.number="form.statement_day" type="number" min="1" max="31" required inputmode="numeric" :aria-invalid="!!error" />
          <span class="field-hint">{{ t('creditCards.monthDayHint') }}</span>
        </div>
        <div class="field">
          <label for="credit-card-due-day">{{ t('creditCards.dueDay') }}</label>
          <input id="credit-card-due-day" v-model.number="form.due_day" type="number" min="1" max="31" required inputmode="numeric" :aria-invalid="!!error" />
          <span class="field-hint">{{ t('creditCards.dueDayHint') }}</span>
        </div>
        <div class="field field-wide">
          <label for="credit-card-remind-days">{{ t('creditCards.remindDaysBefore') }}</label>
          <input id="credit-card-remind-days" v-model="form.remind_days_before" inputmode="numeric" autocomplete="off" :placeholder="t('creditCards.remindPlaceholder')" :aria-invalid="!!error" />
          <span class="field-hint">{{ t('creditCards.remindHint') }}</span>
        </div>
        <div class="field field-wide">
          <label for="credit-card-credit-limit">{{ t('creditCards.creditLimit') }}</label>
          <input id="credit-card-credit-limit" v-model.number="form.credit_limit" type="number" min="0" step="0.01" inputmode="decimal" autocomplete="off" :placeholder="t('creditCards.creditLimitPlaceholder')" :aria-invalid="!!error" />
          <span class="field-hint">{{ t('creditCards.creditLimitHint') }}</span>
        </div>
        <div class="field">
          <label for="credit-card-fee-anchor">{{ t('creditCards.feeWaiverAnchor') }}</label>
          <input id="credit-card-fee-anchor" v-model="form.fee_waiver_anchor_date" type="date" autocomplete="off" />
          <span class="field-hint">{{ t('creditCards.feeWaiverAnchorHint') }}</span>
        </div>
        <div class="field">
          <label for="credit-card-fee-count">{{ t('creditCards.feeWaiverCount') }}</label>
          <input id="credit-card-fee-count" v-model.number="form.fee_waiver_target_count" type="number" min="1" max="99" step="1" inputmode="numeric" autocomplete="off" :placeholder="t('creditCards.feeWaiverCountPlaceholder')" :aria-invalid="!!error" />
        </div>
        <div class="field field-wide">
          <label for="credit-card-fee-amount">{{ t('creditCards.feeWaiverAmount') }}</label>
          <input id="credit-card-fee-amount" v-model.number="form.fee_waiver_target_amount" type="number" min="0" step="0.01" inputmode="decimal" autocomplete="off" :placeholder="t('creditCards.feeWaiverAmountPlaceholder')" :aria-invalid="!!error" />
          <span class="field-hint">{{ t('creditCards.feeWaiverHint') }}</span>
        </div>
      </div>

      <div class="switches">
        <label class="switch-row" for="credit-card-active">
          <input id="credit-card-active" v-model="form.is_active" type="checkbox" />
          <span><strong>{{ t('creditCards.isActive') }}</strong><small>{{ t('creditCards.isActiveHint') }}</small></span>
        </label>
        <label class="switch-row" for="credit-card-calendar">
          <input id="credit-card-calendar" v-model="form.show_in_calendar" type="checkbox" />
          <span><strong>{{ t('creditCards.showInCalendar') }}</strong><small>{{ t('creditCards.showInCalendarHint') }}</small></span>
        </label>
      </div>

      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
    </form>

    <template #footer>
      <button type="button" class="btn ghost" :disabled="pending" @click="$emit('close')">{{ t('creditCards.cancel') }}</button>
      <button type="submit" form="credit-card-form" class="btn" :disabled="pending">
        {{ pending ? t('common.processing') : t('creditCards.save') }}
      </button>
    </template>
  </AppModal>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppModal from '../AppModal.vue'
import { parseLastFours, remainingLastFoursText } from '../../utils/creditCardFormLogic'

const props = defineProps({
  card: { type: Object, default: null },
  pending: { type: Boolean, default: false },
  error: { type: [String, Object], default: '' }
})

const emit = defineEmits(['close', 'save'])
const { t } = useI18n()
const form = reactive(blankForm())
const isEditing = computed(() => Boolean(props.card?.id))

function blankForm() {
  return {
    display_name: '',
    bank_name: '',
    last_four: '',
    statement_day: 1,
    due_day: 20,
    remind_days_before: '',
    credit_limit: null,
    fee_waiver_anchor_date: '',
    fee_waiver_target_count: null,
    fee_waiver_target_amount: null,
    is_active: true,
    show_in_calendar: true
  }
}

function reset(card) {
  Object.assign(form, blankForm(), card || {})
  // API 返回的是整数数组；表单用逗号分隔文本编辑，回显时转回文本。
  if (Array.isArray(form.remind_days_before)) {
    form.remind_days_before = form.remind_days_before.join(', ')
  }
}

watch(() => props.card, reset, { immediate: true })

// 部分失败后父级带回剩余尾号：收缩输入框到未成功部分，
// 让"直接再点保存"只重试失败的卡，不重复创建已成功的。
watch(
  () => props.error,
  (value) => {
    const remainingText = remainingLastFoursText(value)
    if (remainingText !== null && !props.card?.id) {
      form.last_four = remainingText
    }
  }
)

const errorMessage = computed(() =>
  typeof props.error === 'object' && props.error !== null ? props.error.message || '' : props.error || ''
)

function onModalChange(value) {
  if (!value) emit('close')
}

function validDay(value) {
  const day = Number(value)
  return Number.isInteger(day) && day >= 1 && day <= 31
}

function submit() {
  const displayName = form.display_name.trim()
  const bankName = form.bank_name.trim()
  if (!displayName || !bankName) return emit('save', null, t('creditCards.nameRequired'))

  // 尾号：编辑单卡只允许一个值；新建允许多值（1234,2234）一次建多张卡。
  const lastFours = parseLastFours(form.last_four)
  if (lastFours.some((value) => !/^\d{4}$/.test(value))) {
    return emit('save', null, t('creditCards.lastFourInvalid'))
  }
  if (isEditing.value && lastFours.length > 1) {
    return emit('save', null, t('creditCards.lastFourInvalid'))
  }

  if (!validDay(form.statement_day) || !validDay(form.due_day)) return emit('save', null, t('creditCards.dayInvalid'))

  const remindText = String(form.remind_days_before ?? '').trim()
  const remindDays = remindText
    ? remindText.split(/[,，\s]+/).filter(Boolean).map(Number)
    : []
  if (
    remindDays.some((day) => !Number.isInteger(day) || day < 0 || day > 30) ||
    remindDays.length > 8
  ) {
    return emit('save', null, t('creditCards.remindInvalid'))
  }

  // 额度：空字符串/空输入归一为 null（未填写），非负数由输入框 min 约束兜底。
  const limit = form.credit_limit
  const creditLimit =
    limit === null || limit === undefined || limit === '' ? null : Number(limit)

  emit('save', {
    ...form,
    display_name: displayName,
    bank_name: bankName,
    last_fours: lastFours,
    last_four: lastFours[0] ?? '',
    remind_days_before: remindDays,
    credit_limit: creditLimit
  })
}
</script>

<style scoped>
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px 14px; }
.field { min-width: 0; }
.field-wide { grid-column: 1 / -1; }
.field-hint { display: block; margin-top: 5px; color: var(--text-soft); font-size: 11px; line-height: 1.45; }
.switches { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }
.switch-row { display: flex; min-width: 0; align-items: flex-start; gap: 10px; margin: 0; padding: 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); color: var(--text); cursor: pointer; }
.switch-row input { width: 18px; min-height: 18px; flex: 0 0 18px; margin: 2px 0 0; accent-color: var(--primary); }
.switch-row span { display: flex; min-width: 0; flex-direction: column; gap: 3px; }
.switch-row strong { font-size: 13px; }
.switch-row small { color: var(--text-soft); font-size: 11px; line-height: 1.45; }
.form-error { margin: 12px 0 0; color: var(--danger-text); font-size: 13px; }
@media (max-width: 560px) {
  .form-grid, .switches { grid-template-columns: 1fr; }
  .field-wide { grid-column: auto; }
}
</style>
