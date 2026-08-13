<template>
  <div>
    <div class="head">
      <div>
        <h1 tabindex="-1">{{ t('iconLib.title') }}</h1>
        <p class="muted">{{ t('iconLib.subtitle') }}</p>
      </div>
      <div class="row actions-top">
        <button type="button" class="btn ghost" :disabled="loading" @click="load">{{ t('iconLib.refresh') }}</button>
        <button type="button" class="btn ghost" :disabled="startJob || job?.status === 'running'" @click="startPrewarm('missing', true)">{{ t('iconLib.fetchMissing') }}</button>
        <button type="button" class="btn ghost" :disabled="startJob || job?.status === 'running'" @click="startPrewarm('all', true)">{{ t('iconLib.fetchAll') }}</button>
        <button type="button" class="btn" @click="openNew">+ {{ t('iconLib.add') }}</button>
      </div>
    </div>

    <div v-if="loading && !loaded" class="muted">{{ t('common.loading') }}</div>
    <div v-else-if="loadError && !loaded" class="card load-error" role="alert">
      <p>{{ t('iconLib.loadFailed') }}</p>
      <button type="button" class="btn ghost" @click="load">{{ t('iconLib.refresh') }}</button>
    </div>
    <template v-else>
      <p v-if="loadError" class="feedback err" role="status">{{ t('iconLib.refreshFailed') }}</p>
      <div class="grid stats">
        <div class="card stat"><b>{{ items.length }}</b><span>{{ t('iconLib.total') }}</span></div>
        <div class="card stat ok"><b>{{ activeCount }}</b><span>{{ t('iconLib.active') }}</span></div>
        <div class="card stat muted-stat"><b>{{ inactiveCount }}</b><span>{{ t('iconLib.inactive') }}</span></div>
        <div class="card stat"><b>{{ cachedCount }}</b><span>{{ t('iconLib.cached') }}</span></div>
        <div class="card stat warn"><b>{{ missingCount }}</b><span>{{ t('iconLib.missing') }}</span></div>
      </div>

      <div class="card progress-card" v-if="job">
        <div class="progress-head">
          <h3>{{ t('iconLib.progress') }}</h3>
          <span class="tag" :class="job.status">{{ job.status === 'running' ? t('iconLib.running') : t('iconLib.done') }}</span>
        </div>
        <div class="progress-line" role="progressbar" :aria-label="t('iconLib.progress')" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="progressPct"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
        <div class="progress-meta">
          <span>{{ job.done }} / {{ job.total }}</span>
          <span>{{ t('iconLib.success') }} {{ job.success }}</span>
          <span>{{ t('iconLib.failed') }} {{ job.failed }}</span>
          <span>{{ t('iconLib.skipped') }} {{ job.skipped }}</span>
        </div>
        <p v-if="job.current" class="muted">{{ t('iconLib.current') }}：{{ job.current.name }} / {{ job.current.slug }}</p>
        <details v-if="job.items?.length" class="job-details">
          <summary>{{ t('iconLib.details') }}</summary>
          <div class="job-list">
            <div v-for="(it, idx) in job.items.slice(-80)" :key="idx" class="job-row">
              <span class="tag" :class="it.status">{{ it.status }}</span>
              <span class="job-name">{{ it.name }}</span>
              <span class="muted">{{ it.provider }} {{ it.ext || '' }} {{ it.error || '' }}</span>
            </div>
          </div>
        </details>
      </div>

      <div class="bar">
        <div class="seg">
          <button type="button" :class="{ on: activeFilter === 'all' }" :aria-pressed="activeFilter === 'all'" :aria-label="`${t('iconLib.status')}：${t('iconLib.filterAll')}`" @click="activeFilter = 'all'">{{ t('iconLib.filterAll') }}</button>
          <button type="button" :class="{ on: activeFilter === 'active' }" :aria-pressed="activeFilter === 'active'" :aria-label="`${t('iconLib.status')}：${t('iconLib.filterActive')}`" @click="activeFilter = 'active'">{{ t('iconLib.filterActive') }}</button>
          <button type="button" :class="{ on: activeFilter === 'inactive' }" :aria-pressed="activeFilter === 'inactive'" :aria-label="`${t('iconLib.status')}：${t('iconLib.filterInactive')}`" @click="activeFilter = 'inactive'">{{ t('iconLib.filterInactive') }}</button>
        </div>
        <div class="seg">
          <button type="button" :class="{ on: cacheFilter === 'all' }" :aria-pressed="cacheFilter === 'all'" :aria-label="`${t('iconLib.cached')}：${t('iconLib.filterAll')}`" @click="cacheFilter = 'all'">{{ t('iconLib.filterAll') }}</button>
          <button type="button" :class="{ on: cacheFilter === 'cached' }" :aria-pressed="cacheFilter === 'cached'" :aria-label="`${t('iconLib.cached')}：${t('iconLib.filterCached')}`" @click="cacheFilter = 'cached'">{{ t('iconLib.filterCached') }}</button>
          <button type="button" :class="{ on: cacheFilter === 'missing' }" :aria-pressed="cacheFilter === 'missing'" :aria-label="`${t('iconLib.cached')}：${t('iconLib.filterMissing')}`" @click="cacheFilter = 'missing'">{{ t('iconLib.filterMissing') }}</button>
        </div>
        <label for="icon-category-filter" class="sr-only">{{ t('iconLib.category') }}</label>
        <select id="icon-category-filter" v-model="categoryFilter" name="category_filter">
          <option value="">{{ t('iconLib.category') }}: {{ t('iconLib.filterAll') }}</option>
          <option v-for="c in categories" :key="c.key" :value="c.key">{{ c.label }}</option>
        </select>
        <label for="icon-search" class="sr-only">{{ t('iconLib.searchPh') }}</label>
        <input id="icon-search" v-model.trim="q" name="search" :placeholder="t('iconLib.searchPh')" class="search" />
      </div>

      <div class="result-summary" role="status">
        <span>{{ t('iconLib.resultCount', { shown: shown.length, total: items.length }) }}</span>
        <button v-if="hasFilters" type="button" class="btn sm ghost" @click="clearFilters">{{ t('iconLib.clearFilters') }}</button>
      </div>

      <div v-if="isDesktop" class="card table-card">
        <table>
          <thead><tr>
            <th>{{ t('iconLib.icon') }}</th>
            <th>{{ t('iconLib.name') }}</th>
            <th>{{ t('iconLib.domain') }}</th>
            <th>{{ t('iconLib.category') }}</th>
            <th>{{ t('iconLib.slug') }}</th>
            <th>{{ t('iconLib.status') }}</th>
            <th>{{ t('iconLib.actions') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="svc in shown" :key="svc.id">
              <td><ServiceIcon :src="svc.icon" :name="svc.name" class="svc-ico" loading="lazy" decoding="async" /></td>
              <td><b>{{ svc.name }}</b><div class="muted small">{{ svc.source === 'builtin' ? t('iconLib.builtin') : t('iconLib.custom') }}</div></td>
              <td><a :href="svc.website || `https://${svc.domain}`" target="_blank" rel="noopener">{{ svc.domain }}</a></td>
              <td>
                <div class="cat-tags">
                  <span v-for="label in getServiceCategoryLabels(svc, categories)" :key="label" class="tag">{{ label }}</span>
                </div>
              </td>
              <td><code>{{ svc.slug }}</code><div class="muted small">{{ svc.cached ? `${t('iconLib.cached')} ${svc.cached_ext || ''}` : t('iconLib.missing') }}</div></td>
              <td><span class="tag" :class="svc.is_active ? 'ok' : 'off'">{{ svc.is_active ? t('iconLib.active') : t('iconLib.inactive') }}</span></td>
              <td class="acts">
                <button type="button" class="btn sm ghost" :disabled="isRowBusy(svc.id)" @click="openEdit(svc)">{{ t('iconLib.edit') }}</button>
                <button type="button" class="btn sm ghost" :disabled="isRowBusy(svc.id)" @click="fetchOne(svc)">{{ t('iconLib.fetchOne') }}</button>
                <button v-if="svc.is_active" type="button" class="btn sm danger" :disabled="isRowBusy(svc.id)" @click="deactivate(svc)">{{ t('iconLib.deactivate') }}</button>
                <button v-else type="button" class="btn sm ghost" :disabled="isRowBusy(svc.id)" @click="restore(svc)">{{ t('iconLib.activate') }}</button>
              </td>
            </tr>
            <tr v-if="!shown.length"><td colspan="7" class="muted table-empty">{{ t('iconLib.noFilterResults') }}</td></tr>
          </tbody>
        </table>
      </div>

      <div v-else-if="shown.length" class="service-cards" role="list">
        <article v-for="svc in shown" :key="svc.id" class="card service-card" role="listitem">
          <div class="service-card-head">
            <ServiceIcon :src="svc.icon" :name="svc.name" class="svc-ico card-icon" loading="lazy" decoding="async" />
            <div class="service-card-title">
              <b>{{ svc.name }}</b>
              <span class="muted small">{{ svc.source === 'builtin' ? t('iconLib.builtin') : t('iconLib.custom') }}</span>
            </div>
            <span class="tag" :class="svc.is_active ? 'ok' : 'off'">{{ svc.is_active ? t('iconLib.active') : t('iconLib.inactive') }}</span>
          </div>
          <a class="service-domain" :href="svc.website || `https://${svc.domain}`" target="_blank" rel="noopener">{{ svc.domain }}</a>
          <div class="cat-tags">
            <span v-for="(label, index) in getServiceCategoryLabels(svc, categories)" :key="`${getServiceCategoryKeys(svc)[index]}-${index}`" class="tag">{{ label }}</span>
          </div>
          <div class="service-meta"><code>{{ svc.slug }}</code><span class="muted small">{{ svc.cached ? `${t('iconLib.cached')} ${svc.cached_ext || ''}` : t('iconLib.missing') }}</span></div>
          <div class="acts">
            <button type="button" class="btn sm ghost" :disabled="isRowBusy(svc.id)" @click="openEdit(svc)">{{ t('iconLib.edit') }}</button>
            <button type="button" class="btn sm ghost" :disabled="isRowBusy(svc.id)" @click="fetchOne(svc)">{{ t('iconLib.fetchOne') }}</button>
            <button v-if="svc.is_active" type="button" class="btn sm danger" :disabled="isRowBusy(svc.id)" @click="deactivate(svc)">{{ t('iconLib.deactivate') }}</button>
            <button v-else type="button" class="btn sm ghost" :disabled="isRowBusy(svc.id)" @click="restore(svc)">{{ t('iconLib.activate') }}</button>
          </div>
        </article>
      </div>
      <div v-else class="card empty-services"><p class="muted">{{ t('iconLib.noFilterResults') }}</p></div>
    </template>

    <AppModal v-model="showForm" :title="editing ? t('iconLib.formTitleEdit') : t('iconLib.formTitleNew')" :close-label="t('common.close')" :pending="saving">
      <form id="icon-service-form" @submit.prevent="save">
        <p v-if="formErr" class="err" role="alert">{{ formErr }}</p>
        <label for="icon-service-name">{{ t('iconLib.name') }}</label>
        <input id="icon-service-name" v-model.trim="form.name" name="name" :placeholder="t('iconLib.namePh')" />
        <label for="icon-service-domain">{{ t('iconLib.domain') }}</label>
        <input id="icon-service-domain" v-model.trim="form.domain" name="domain" :placeholder="t('iconLib.domainPh')" />
        <label for="icon-service-website">{{ t('iconLib.website') }}</label>
        <input id="icon-service-website" v-model.trim="form.website" name="website" :placeholder="t('iconLib.websitePh')" />
        <span id="icon-service-category-label" class="field-label">{{ t('iconLib.category') }}</span>
        <div class="category-checks" role="group" aria-labelledby="icon-service-category-label">
          <label v-for="c in categories" :key="c.key" class="category-check" :for="`icon-service-category-${c.key}`">
            <input :id="`icon-service-category-${c.key}`" v-model="form.category_keys" name="category_keys" type="checkbox" :value="c.key" />
            <span>{{ c.label }}</span>
          </label>
        </div>
        <p class="muted small">{{ t('iconLib.categoryMultiHint') }}</p>
        <label for="icon-service-slug">{{ t('iconLib.slug') }}</label>
        <input id="icon-service-slug" v-model.trim="form.slug" name="slug" :placeholder="t('iconLib.slugPh')" />
        <p class="muted small">{{ t('iconLib.slugWarn') }}</p>
        <div class="row">
          <label for="icon-service-sort" style="flex:1">{{ t('iconLib.sort') }}<input id="icon-service-sort" v-model.number="form.sort" name="sort" type="number" /></label>
          <label for="icon-service-active" class="check"><input id="icon-service-active" v-model="form.is_active" name="is_active" type="checkbox" /> {{ t('iconLib.active') }}</label>
        </div>
      </form>
      <template #footer>
        <button type="submit" form="icon-service-form" class="btn" :disabled="saving">
          {{ saving ? t('common.processing') : t('iconLib.save') }}
        </button>
        <button type="button" class="btn ghost" :disabled="saving" @click="showForm = false">{{ t('iconLib.cancel') }}</button>
      </template>
    </AppModal>

    <AppModal
      v-model="confirmDialogOpen"
      :title="confirm.state.value?.title || ''"
      width="400px"
      :close-label="t('common.close')"
      :pending="confirm.state.value?.pending"
      description-id="icon-confirm-description"
      @close="confirm.close"
    >
      <p id="icon-confirm-description" style="font-size:14px;line-height:1.6">{{ confirm.state.value?.message }}</p>
      <p v-if="confirm.state.value?.error" class="err" role="alert">{{ confirm.state.value.error }}</p>
      <template #footer>
        <button type="button" class="btn ghost" :disabled="confirm.state.value?.pending" @click="confirm.close">{{ t('iconLib.cancel') }}</button>
        <button type="button" class="btn danger" :disabled="confirm.state.value?.pending" @click="confirm.confirm">
          {{ confirm.state.value?.pending ? t('common.processing') : t('common.confirm') }}
        </button>
      </template>
    </AppModal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import ServiceIcon from '../components/ServiceIcon.vue'
import AppModal from '../components/AppModal.vue'
import { useConfirm } from '../composables/useConfirm'
import { useBreakpoint } from '../composables/useBreakpoint'
import { getServiceCategoryKeys, getServiceCategoryLabels } from '../utils/serviceLibrary'

const { t } = useI18n()
const isDesktop = useBreakpoint('(min-width: 721px)')
const loading = ref(true)
const loaded = ref(false)
const loadError = ref(false)
const items = ref([])
const categories = ref([])
const q = ref('')
const activeFilter = ref('all')
const cacheFilter = ref('all')
const categoryFilter = ref('')
const showForm = ref(false)
const editing = ref(null)
const formErr = ref('')
const form = ref({})
const saving = ref(false)
const startJob = ref(false)
const rowBusyIds = ref(new Set())
const job = ref(null)
const confirm = useConfirm()
const confirmDialogOpen = computed({
  get: () => !!confirm.state.value?.open,
  set: (v) => { if (!v) confirm.close() }
})
let pollTimer = null

const activeCount = computed(() => items.value.filter((x) => x.is_active).length)
const inactiveCount = computed(() => items.value.length - activeCount.value)
const cachedCount = computed(() => items.value.filter((x) => x.cached).length)
const missingCount = computed(() => items.value.length - cachedCount.value)
const progressPct = computed(() => job.value?.total ? Math.round((job.value.done / job.value.total) * 100) : 0)

const hasFilters = computed(() => activeFilter.value !== 'all' || cacheFilter.value !== 'all' || Boolean(categoryFilter.value || q.value))

function clearFilters() {
  activeFilter.value = 'all'
  cacheFilter.value = 'all'
  categoryFilter.value = ''
  q.value = ''
}

const shown = computed(() => {
  let out = items.value.slice()
  if (activeFilter.value === 'active') out = out.filter((x) => x.is_active)
  if (activeFilter.value === 'inactive') out = out.filter((x) => !x.is_active)
  if (cacheFilter.value === 'cached') out = out.filter((x) => x.cached)
  if (cacheFilter.value === 'missing') out = out.filter((x) => !x.cached)
  if (categoryFilter.value) out = out.filter((x) => getServiceCategoryKeys(x).includes(categoryFilter.value))
  const s = q.value.toLowerCase()
  if (s) out = out.filter((x) => x.name.toLowerCase().includes(s) || x.domain.toLowerCase().includes(s) || x.slug.toLowerCase().includes(s))
  return out
})

function selectedCategoryKeys() {
  const keys = Array.isArray(form.value.category_keys) ? form.value.category_keys : getServiceCategoryKeys(form.value)
  return keys.map((x) => String(x || '').trim()).filter(Boolean)
}

function blank() {
  const category = categories.value[0]?.key || 'other'
  return { name: '', domain: '', website: '', category, category_keys: [category], slug: '', is_active: true, sort: 0 }
}

async function load() {
  if (loading.value && loaded.value) return
  loading.value = true
  loadError.value = false
  try {
    const [svc, cat] = await Promise.allSettled([
      api.get('/api/admin/icon-services'),
      api.get('/api/admin/icon-services/categories')
    ])
    if (svc.status === 'rejected') {
      loadError.value = true
      return
    }
    items.value = svc.value.data
    loaded.value = true
    if (cat.status === 'fulfilled') categories.value = cat.value.data
  } finally {
    loading.value = false
  }
}

function isRowBusy(id) { return rowBusyIds.value.has(id) }
function setRowBusy(id, busy) {
  const next = new Set(rowBusyIds.value)
  if (busy) next.add(id)
  else next.delete(id)
  rowBusyIds.value = next
}
function openNew() {
  if (saving.value) return
  editing.value = null; formErr.value = ''; form.value = blank(); showForm.value = true
}
function openEdit(svc) {
  if (!svc || saving.value || isRowBusy(svc.id)) return
  editing.value = svc
  formErr.value = ''
  form.value = { ...svc, category_keys: getServiceCategoryKeys(svc) }
  showForm.value = true
}

async function save() {
  if (saving.value) return
  if (!form.value.name) return (formErr.value = t('iconLib.nameReq'))
  if (!form.value.domain) return (formErr.value = t('iconLib.domainReq'))
  const keys = selectedCategoryKeys()
  if (!keys.length) return (formErr.value = t('iconLib.categoryReq'))
  const payload = { ...form.value, category: keys[0], category_keys: keys, website: form.value.website || null, slug: form.value.slug || null }
  saving.value = true
  formErr.value = ''
  try {
    if (editing.value) await api.patch(`/api/admin/icon-services/${editing.value.id}`, payload)
    else await api.post('/api/admin/icon-services', payload)
    showForm.value = false
    await load()
  } catch (e) {
    formErr.value = e?.response?.data?.detail || String(e)
  } finally {
    saving.value = false
  }
}

async function deactivate(svc) {
  if (!svc || isRowBusy(svc.id)) return
  confirm.open({
    title: t('iconLib.deactivate'),
    message: t('iconLib.confirmDeactivate'),
    danger: true,
    onConfirm: async () => {
      if (isRowBusy(svc.id)) return
      setRowBusy(svc.id, true)
      try {
        await api.delete(`/api/admin/icon-services/${svc.id}`)
        await load()
      } finally {
        setRowBusy(svc.id, false)
      }
    }
  })
}
async function restore(svc) {
  if (!svc || isRowBusy(svc.id)) return
  setRowBusy(svc.id, true)
  try { await api.post(`/api/admin/icon-services/${svc.id}/restore`); await load() }
  finally { setRowBusy(svc.id, false) }
}
async function fetchOne(svc) {
  if (!svc || isRowBusy(svc.id)) return
  setRowBusy(svc.id, true)
  try { await api.post(`/api/admin/icon-services/${svc.id}/prewarm`, null, { params: { force: true } }); await load() }
  finally { setRowBusy(svc.id, false) }
}

async function startPrewarm(mode, force = false) {
  if (startJob.value || job.value?.status === 'running') return
  const run = async () => {
    if (startJob.value || job.value?.status === 'running') return
    startJob.value = true
    try {
      const { data } = await api.post('/api/admin/icon-services/prewarm', { mode, force })
      job.value = data
      startPoll(data.id)
    } finally {
      startJob.value = false
    }
  }
  if (mode === 'all') {
    confirm.open({
      title: t('iconLib.fetchAll'),
      message: t('iconLib.confirmFetchAll'),
      danger: true,
      onConfirm: run
    })
    return
  }
  await run()
}

function startPoll(id) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    const { data } = await api.get(`/api/admin/icon-services/prewarm/${id}`)
    job.value = data
    if (data.status !== 'running') {
      clearInterval(pollTimer); pollTimer = null
      await load()
    }
  }, 1500)
}

onMounted(load)
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.head { align-items:flex-start; margin-bottom:16px; }
h1 { margin:0; }
.actions-top { justify-content:flex-end; flex-wrap:wrap; }
.stats { grid-template-columns: repeat(5, 1fr); margin-bottom:14px; }
.stat { display:flex; flex-direction:column; gap:4px; }
.stat b { font-size:24px; }
.stat span { color:var(--text-soft); font-size:13px; }
.progress-card { margin-bottom:14px; }
.progress-head { display:flex; justify-content:space-between; align-items:center; }
.progress-head h3 { margin:0; }
.progress-line { height:10px; border-radius:999px; background:var(--surface-2); overflow:hidden; margin:12px 0; }
.progress-fill { height:100%; background:linear-gradient(90deg,var(--primary),var(--primary-2)); transition:width .2s ease; }
.progress-meta { display:flex; gap:14px; flex-wrap:wrap; font-size:13px; }
.job-details { margin-top:10px; }
.job-list { max-height:210px; overflow:auto; display:flex; flex-direction:column; gap:4px; margin-top:8px; }
.job-row { display:flex; gap:8px; align-items:center; font-size:12px; }
.job-name { min-width:150px; font-weight:600; }
.bar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
.seg { background:var(--surface-2); border-radius:10px; padding:3px; }
.seg button { padding:6px 10px; border-radius:8px; }
.search { max-width:280px; }
.result-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 0 10px; color: var(--text-soft); font-size: 13px; }
.table-card { overflow:auto; }
.table-empty { text-align: center; }
.service-cards { display: grid; gap: 12px; }
.service-card { display: grid; gap: 12px; }
.service-card-head { display: flex; align-items: center; gap: 10px; }
.service-card-title { display: flex; flex: 1; flex-direction: column; min-width: 0; }
.card-icon { width: 44px !important; height: 44px !important; }
.service-domain { overflow-wrap: anywhere; }
.service-meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.empty-services { text-align: center; }
.svc-ico { width:30px; height:30px; border-radius:8px; border:1px solid var(--border); object-fit:contain; background:var(--surface-2); }
.small { font-size:12px; }
.acts { display:flex; gap:6px; flex-wrap:wrap; }
.cat-tags { display:flex; gap:6px; flex-wrap:wrap; }
.category-checks { display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:8px; margin-top:8px; }
.category-check { display:flex !important; align-items:center; gap:8px; margin:0 !important; padding:8px 10px; border:1px solid var(--border); border-radius:10px; background:var(--surface-2); font-size:13px; }
.category-check input { width:auto; }
.field-label { display:block; margin-top:10px; font-size:13px; font-weight:600; }
.tag.ok, .tag.success { background:#dcfce7; color:#166534; }
.tag.off, .tag.failed { background:#fee2e2; color:#991b1b; }
.tag.skipped { background:#fef3c7; color:#92400e; }
.tag.running { background:var(--primary-soft); color:var(--primary); }
.modal label { display:block; margin-top:10px; font-size:13px; font-weight:600; }
.check { display:flex !important; align-items:center; gap:6px; margin-top:26px !important; }
.check input { width:auto; }
.modal-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:16px; }
@media (max-width: 900px) { .stats { grid-template-columns: repeat(2, 1fr); } .head { flex-direction:column; } }
@media (max-width: 720px) {
  .actions-top { width: 100%; }
  .actions-top .btn { flex: 1 1 calc(50% - 6px); min-height: 44px; }
  .bar { flex-direction: column; align-items: stretch; }
  .bar .seg, .bar select { width: 100%; }
  .search { width: 100%; max-width: none; }
  .acts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .acts .btn.sm { min-height: 44px; }
}
</style>
