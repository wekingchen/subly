<template>
  <section class="card reference-card" aria-labelledby="category-manager-title">
    <div class="reference-head">
      <div>
        <h2 id="category-manager-title"><span class="reference-signal"></span>{{ t('settings.categoryManager') }}</h2>
        <p class="muted">{{ t('settings.categoryManagerTip') }}</p>
      </div>
      <button type="button" class="btn ghost sm" @click="openCreate">{{ t('settings.addCategory') }}</button>
    </div>

    <div class="reference-list">
      <div v-for="item in items" :key="item.id" class="reference-row">
        <span class="reference-icon" :style="{ color: item.color || 'inherit' }">{{ item.icon || '📦' }}</span>
        <div class="reference-main">
          <b>{{ item.name }}</b>
          <span class="muted">{{ item.is_system ? t('settings.systemItem') : t('settings.customItem') }}</span>
        </div>
        <div v-if="!item.is_system" class="reference-actions">
          <button type="button" class="btn ghost sm" @click="openEdit(item)">{{ t('settings.editItem') }}</button>
          <button type="button" class="btn danger sm" @click="requestDelete(item)">{{ t('sub.delete') }}</button>
        </div>
      </div>
      <p v-if="!items.length && !loading" class="muted reference-empty">{{ t('settings.noCategories') }}</p>
    </div>
    <p v-if="message" class="feedback" :class="ok ? 'ok' : 'err'" role="status">{{ message }}</p>

    <AppModal v-model="formOpen" :title="editingId ? t('settings.editCategory') : t('settings.addCategory')" :close-label="t('common.close')">
      <label for="category-name">{{ t('sub.name') }}</label>
      <input id="category-name" v-model="form.name" maxlength="64" />
      <div class="reference-form-grid">
        <div>
          <label for="category-icon">{{ t('sub.icon') }}</label>
          <input id="category-icon" v-model="form.icon" maxlength="128" />
        </div>
        <div>
          <label for="category-color">{{ t('settings.categoryColor') }}</label>
          <input id="category-color" v-model="form.color" type="color" />
        </div>
      </div>
      <p v-if="formError" class="feedback err" role="alert">{{ formError }}</p>
      <template #footer>
        <button type="button" class="btn ghost" @click="formOpen = false">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn" :disabled="saving" @click="save">{{ t('sub.save') }}</button>
      </template>
    </AppModal>

    <AppModal
      v-model="confirmOpen"
      :title="confirm.state.value?.title || ''"
      :close-label="t('common.close')"
      @close="confirm.reset"
    >
      <p>{{ confirm.state.value?.message }}</p>
      <template #footer>
        <button type="button" class="btn ghost" @click="confirm.reset">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn danger" @click="confirm.confirm">{{ t('common.confirm') }}</button>
      </template>
    </AppModal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import { useConfirm } from '../../composables/useConfirm'
import AppModal from '../AppModal.vue'

const emit = defineEmits(['changed'])
const { t } = useI18n()
const confirm = useConfirm()
const confirmOpen = computed({
  get: () => Boolean(confirm.state.value?.open),
  set: (value) => { if (!value) confirm.reset() }
})
const items = ref([])
const loading = ref(false)
const saving = ref(false)
const formOpen = ref(false)
const editingId = ref(null)
const message = ref('')
const ok = ref(true)
const formError = ref('')
const form = reactive({ name: '', icon: '📦', color: '#6b7280', sort: 0 })

async function load() {
  loading.value = true
  try { items.value = (await api.get('/api/categories')).data || [] }
  catch (error) { ok.value = false; message.value = error.response?.data?.detail || t('common.networkError') }
  finally { loading.value = false }
}

function resetForm(item = null) {
  editingId.value = item?.id || null
  form.name = item?.name || ''
  form.icon = item?.icon || '📦'
  form.color = item?.color || '#6b7280'
  form.sort = item?.sort ?? 0
  formError.value = ''
}

function openCreate() { resetForm(); formOpen.value = true }
function openEdit(item) { resetForm(item); formOpen.value = true }

async function save() {
  const name = form.name.trim()
  if (!name) { formError.value = t('settings.nameRequired'); return }
  saving.value = true
  formError.value = ''
  try {
    const payload = { name, icon: form.icon.trim() || null, color: form.color || null, sort: form.sort }
    if (editingId.value) await api.put(`/api/categories/${editingId.value}`, payload)
    else await api.post('/api/categories', payload)
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
    title: t('settings.deleteCategory'),
    message: t('settings.deleteCategoryConfirm', { name: item.name }),
    danger: true,
    onConfirm: async () => {
      try {
        const { data } = await api.delete(`/api/categories/${item.id}`)
        ok.value = true
        message.value = t('settings.referenceDeleted', { n: data.unlinked_subscriptions || 0 })
        await load()
        emit('changed')
      } catch (error) { ok.value = false; message.value = error.response?.data?.detail || t('common.networkError') }
    }
  })
}

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
.reference-icon { width: 34px; text-align: center; font-size: 20px; flex-shrink: 0; }
.reference-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.reference-main b { overflow-wrap: anywhere; }
.reference-main span { font-size: 12px; }
.reference-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.reference-form-grid { display: grid; grid-template-columns: 1fr 120px; gap: 10px; }
.reference-empty, .feedback { margin: 10px 0 0; font-size: 13px; }
.ok { color: var(--success); }
.err { color: var(--danger); }
@media (max-width: 720px) {
  .reference-head, .reference-row { align-items: stretch; flex-direction: column; }
  .reference-head .btn, .reference-actions .btn { min-height: 44px; flex: 1; }
  .reference-actions { justify-content: stretch; }
  .reference-form-grid { grid-template-columns: 1fr; }
}
</style>
