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
          <input id="credit-card-last-four" v-model="form.last_four" maxlength="4" inputmode="numeric" pattern="[0-9]{4}" autocomplete="off" :placeholder="t('creditCards.lastFourPlaceholder')" :aria-invalid="!!error" />
          <span class="field-hint">{{ t('creditCards.lastFourHint') }}</span>
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

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
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
import { reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppModal from '../AppModal.vue'

const props = defineProps({
  card: { type: Object, default: null },
  pending: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

const emit = defineEmits(['close', 'save'])
const { t } = useI18n()
const form = reactive(blankForm())

function blankForm() {
  return {
    display_name: '',
    bank_name: '',
    last_four: '',
    statement_day: 1,
    due_day: 20,
    remind_days_before: '',
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
  const lastFour = form.last_four.trim()
  if (!displayName || !bankName) return emit('save', null, t('creditCards.nameRequired'))
  if (lastFour && !/^\d{4}$/.test(lastFour)) return emit('save', null, t('creditCards.lastFourInvalid'))
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
  emit('save', {
    ...form,
    display_name: displayName,
    bank_name: bankName,
    last_four: lastFour,
    remind_days_before: remindDays
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
