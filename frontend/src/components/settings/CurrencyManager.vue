<template>
  <section class="card reference-card" aria-labelledby="currency-manager-title">
    <div class="reference-head">
      <div>
        <h2 id="currency-manager-title"><span class="reference-signal"></span>{{ t('settings.currencyManager') }}</h2>
        <p class="muted">{{ t('settings.currencyManagerTip') }}</p>
      </div>
      <button type="button" class="btn ghost sm" @click="openCreate">{{ t('settings.addCurrency') }}</button>
    </div>

    <div class="reference-list">
      <div v-for="item in customItems" :key="item.code" class="reference-row">
        <span class="currency-code mono-data">{{ item.code }}</span>
        <div class="reference-main">
          <b>{{ item.symbol }} {{ item.name }}</b>
          <span class="muted">
            {{ item.code === baseCurrency
              ? t('settings.currentBaseCurrency')
              : item.rate_to_user_base == null
                ? t('settings.rateMissing')
                : t('settings.manualRateHint', { code: item.code, base: baseCurrency }) + ` · ${formatRate(item.rate_to_user_base)}` }}
          </span>
        </div>
        <div class="reference-actions">
          <button type="button" class="btn ghost sm" @click="openEdit(item)">{{ t('settings.editItem') }}</button>
          <button type="button" class="btn danger sm" @click="requestDelete(item)">{{ t('sub.delete') }}</button>
        </div>
      </div>
      <p v-if="!customItems.length && !loading" class="muted reference-empty">{{ t('settings.noCustomCurrencies') }}</p>
    </div>
    <p v-if="message" class="feedback" :class="ok ? 'ok' : 'err'" role="status">{{ message }}</p>

    <AppModal v-model="formOpen" :title="editingCode ? t('settings.editCurrency') : t('settings.addCurrency')" :close-label="t('common.close')">
      <div class="currency-form-grid">
        <div>
          <label for="currency-code">{{ t('settings.currencyCode') }}</label>
          <input id="currency-code" v-model="form.code" maxlength="8" :disabled="Boolean(editingCode)" @input="normalizeCode" />
        </div>
        <div>
          <label for="currency-symbol">{{ t('settings.currencySymbol') }}</label>
          <input id="currency-symbol" v-model="form.symbol" maxlength="8" />
        </div>
      </div>
      <label for="currency-name">{{ t('sub.name') }}</label>
      <input id="currency-name" v-model="form.name" maxlength="64" />
      <label for="currency-rate">{{ t('settings.manualRate') }} <span class="muted">({{ t('settings.manualRateHint', { code: form.code || 'CODE', base: baseCurrency }) }})</span></label>
      <input id="currency-rate" v-model="form.rate_to_user_base" type="number" min="0" step="any" inputmode="decimal" :disabled="rateLocked" />
      <p v-if="rateLocked" class="muted rate-lock-hint">{{ t('settings.rateSelfLocked') }}</p>
      <p v-if="formError" class="feedback err" role="alert">{{ formError }}</p>
      <template #footer>
        <button type="button" class="btn ghost" @click="formOpen = false">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn" :disabled="saving" @click="save">{{ t('sub.save') }}</button>
      </template>
    </AppModal>

    <AppModal v-model="confirmOpen" :title="confirm.state.value?.title || ''" :close-label="t('common.close')" @close="confirm.reset">
      <p>{{ confirm.state.value?.message }}</p>
      <template #footer>
        <button type="button" class="btn ghost" @click="confirm.reset">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn danger" @click="confirm.confirm">{{ t('common.confirm') }}</button>
      </template>
    </AppModal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import { useConfirm } from '../../composables/useConfirm'
import AppModal from '../AppModal.vue'

const props = defineProps({ baseCurrency: { type: String, default: 'CNY' } })
const emit = defineEmits(['changed'])
const { t } = useI18n()
const confirm = useConfirm()
const confirmOpen = computed({
  get: () => Boolean(confirm.state.value?.open),
  set: (value) => { if (!value) confirm.reset() }
})
const items = ref([])
const customItems = computed(() => items.value.filter((item) => item.is_custom))
const loading = ref(false)
const saving = ref(false)
const formOpen = ref(false)
const editingCode = ref('')
const originalRate = ref('')
const message = ref('')
const ok = ref(true)
const formError = ref('')
const form = reactive({ code: '', name: '', symbol: '', rate_to_user_base: '' })
let loadRequestId = 0
const rateLocked = computed(() => (
  form.code.trim().toUpperCase() === props.baseCurrency.trim().toUpperCase()
))

function formatRate(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 8 }).format(number)
}

async function load() {
  const requestId = ++loadRequestId
  loading.value = true
  try {
    const data = (await api.get('/api/currencies')).data || []
    if (requestId !== loadRequestId) return
    items.value = data
  } catch (error) {
    if (requestId !== loadRequestId) return
    ok.value = false
    message.value = error.response?.data?.detail || t('common.networkError')
  } finally {
    if (requestId === loadRequestId) loading.value = false
  }
}

function normalizeCode() { form.code = form.code.toUpperCase().replace(/[^A-Z0-9]/g, '') }
function resetForm(item = null) {
  editingCode.value = item?.code || ''
  form.code = item?.code || ''
  form.name = item?.name || ''
  form.symbol = item?.symbol || ''
  form.rate_to_user_base = item?.rate_to_user_base ?? ''
  originalRate.value = form.rate_to_user_base
  formError.value = ''
}
function openCreate() { resetForm(); formOpen.value = true }
function openEdit(item) { resetForm(item); formOpen.value = true }

async function save() {
  normalizeCode()
  if (!form.code) { formError.value = t('settings.codeRequired'); return }
  if (!form.name.trim()) { formError.value = t('settings.nameRequired'); return }
  const rateText = String(form.rate_to_user_base ?? '').trim()
  const rate = rateText ? Number(rateText) : null
  if (rate !== null && (!Number.isFinite(rate) || rate <= 0)) {
    formError.value = t('settings.ratePositive')
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const payload = { name: form.name.trim(), symbol: form.symbol.trim() }
    if (!editingCode.value) payload.code = form.code
    if (
      !rateLocked.value
      && (!editingCode.value || rateText !== String(originalRate.value ?? ''))
    ) {
      payload.rate_to_user_base = rate
    }
    if (editingCode.value) await api.put(`/api/currencies/${editingCode.value}`, payload)
    else await api.post('/api/currencies', payload)
    formOpen.value = false
    ok.value = true
    message.value = t('settings.referenceSaved')
    await load()
    emit('changed')
  } catch (error) { formError.value = error.response?.data?.detail || t('common.networkError') }
  finally { saving.value = false }
}

function requestDelete(item) {
  confirm.open({
    title: t('settings.deleteCurrency'),
    message: t('settings.deleteCurrencyConfirm', { code: item.code }),
    danger: true,
    onConfirm: async () => {
      try {
        await api.delete(`/api/currencies/${item.code}`)
        ok.value = true
        message.value = t('settings.currencyDeleted')
        await load()
        emit('changed')
      } catch (error) { ok.value = false; message.value = error.response?.data?.detail || t('common.networkError') }
    }
  })
}

watch(() => props.baseCurrency, () => {
  formOpen.value = false
  confirm.reset()
  message.value = ''
  formError.value = ''
  ok.value = true
  items.value = []
  load()
})
onMounted(load)
</script>

<style scoped>
.reference-card { overflow: hidden; }
.reference-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.reference-head h2 { display: flex; align-items: center; gap: 9px; margin: 0; font-size: 16px; }
.reference-head p { margin: 5px 0 0; font-size: 13px; line-height: 1.55; }
.reference-signal { width: 9px; height: 9px; border-radius: 999px; background: var(--signal-cyan); box-shadow: 0 0 0 4px color-mix(in srgb, var(--signal-cyan) 13%, transparent); }
.reference-list { display: flex; flex-direction: column; }
.reference-row { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.reference-row:last-child { border-bottom: 0; }
.currency-code { width: 48px; padding: 6px; border: 1px solid var(--border); border-radius: 8px; text-align: center; flex-shrink: 0; }
.reference-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.reference-main b, .reference-main span { overflow-wrap: anywhere; }
.reference-main span { font-size: 12px; }
.reference-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.currency-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.reference-empty, .feedback, .rate-lock-hint { margin: 10px 0 0; font-size: 13px; }
.ok { color: var(--success); }
.err { color: var(--danger); }
@media (max-width: 720px) {
  .reference-head, .reference-row { align-items: stretch; flex-direction: column; }
  .reference-head .btn, .reference-actions .btn { min-height: 44px; flex: 1; }
  .reference-actions { justify-content: stretch; }
  .currency-form-grid { grid-template-columns: 1fr; }
}
</style>
