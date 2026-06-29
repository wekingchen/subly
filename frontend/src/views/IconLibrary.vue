<template>
  <div>
    <div class="head">
      <div>
        <h1>{{ t('iconLib.title') }}</h1>
        <p class="muted">{{ t('iconLib.subtitle') }}</p>
      </div>
      <div class="row actions-top">
        <button class="btn ghost" @click="load">{{ t('iconLib.refresh') }}</button>
        <button class="btn ghost" :disabled="job?.status === 'running'" @click="startPrewarm('missing', true)">{{ t('iconLib.fetchMissing') }}</button>
        <button class="btn ghost" :disabled="job?.status === 'running'" @click="startPrewarm('all', true)">{{ t('iconLib.fetchAll') }}</button>
        <button class="btn" @click="openNew">+ {{ t('iconLib.add') }}</button>
      </div>
    </div>

    <div v-if="loading" class="muted">{{ t('common.loading') }}</div>
    <template v-else>
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
        <div class="progress-line"><div class="progress-fill" :style="{ width: progressPct + '%' }"></div></div>
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
          <button :class="{ on: activeFilter === 'all' }" @click="activeFilter = 'all'">{{ t('iconLib.filterAll') }}</button>
          <button :class="{ on: activeFilter === 'active' }" @click="activeFilter = 'active'">{{ t('iconLib.filterActive') }}</button>
          <button :class="{ on: activeFilter === 'inactive' }" @click="activeFilter = 'inactive'">{{ t('iconLib.filterInactive') }}</button>
        </div>
        <div class="seg">
          <button :class="{ on: cacheFilter === 'all' }" @click="cacheFilter = 'all'">{{ t('iconLib.filterAll') }}</button>
          <button :class="{ on: cacheFilter === 'cached' }" @click="cacheFilter = 'cached'">{{ t('iconLib.filterCached') }}</button>
          <button :class="{ on: cacheFilter === 'missing' }" @click="cacheFilter = 'missing'">{{ t('iconLib.filterMissing') }}</button>
        </div>
        <select v-model="categoryFilter">
          <option value="">{{ t('iconLib.category') }}: {{ t('iconLib.filterAll') }}</option>
          <option v-for="c in categories" :key="c.key" :value="c.key">{{ c.label }}</option>
        </select>
        <input v-model.trim="q" :placeholder="t('iconLib.searchPh')" class="search" />
      </div>

      <div class="card table-card">
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
              <td><span class="tag">{{ svc.category_label || svc.category }}</span></td>
              <td><code>{{ svc.slug }}</code><div class="muted small">{{ svc.cached ? `${t('iconLib.cached')} ${svc.cached_ext || ''}` : t('iconLib.missing') }}</div></td>
              <td><span class="tag" :class="svc.is_active ? 'ok' : 'off'">{{ svc.is_active ? t('iconLib.active') : t('iconLib.inactive') }}</span></td>
              <td class="acts">
                <button class="btn sm ghost" @click="openEdit(svc)">{{ t('iconLib.edit') }}</button>
                <button class="btn sm ghost" @click="duplicate(svc)">{{ t('iconLib.duplicate') }}</button>
                <button class="btn sm ghost" @click="fetchOne(svc)">{{ t('iconLib.fetchOne') }}</button>
                <button v-if="svc.is_active" class="btn sm danger" @click="deactivate(svc)">{{ t('iconLib.deactivate') }}</button>
                <button v-else class="btn sm ghost" @click="restore(svc)">{{ t('iconLib.activate') }}</button>
              </td>
            </tr>
            <tr v-if="!shown.length"><td colspan="7" class="muted" style="text-align:center">{{ t('iconLib.missing') }}</td></tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
      <div class="modal">
        <h3>{{ editing ? t('iconLib.formTitleEdit') : t('iconLib.formTitleNew') }}</h3>
        <p v-if="formErr" class="err">{{ formErr }}</p>
        <label>{{ t('iconLib.name') }}</label>
        <input v-model.trim="form.name" :placeholder="t('iconLib.namePh')" />
        <label>{{ t('iconLib.domain') }}</label>
        <input v-model.trim="form.domain" :placeholder="t('iconLib.domainPh')" />
        <label>{{ t('iconLib.website') }}</label>
        <input v-model.trim="form.website" :placeholder="t('iconLib.websitePh')" />
        <label>{{ t('iconLib.category') }}</label>
        <select v-model="form.category">
          <option v-for="c in categories" :key="c.key" :value="c.key">{{ c.label }}</option>
        </select>
        <label>{{ t('iconLib.slug') }}</label>
        <input v-model.trim="form.slug" :placeholder="t('iconLib.slugPh')" />
        <p class="muted small">{{ t('iconLib.slugWarn') }}</p>
        <div class="row">
          <label style="flex:1">{{ t('iconLib.sort') }}<input v-model.number="form.sort" type="number" /></label>
          <label class="check"><input v-model="form.is_active" type="checkbox" /> {{ t('iconLib.active') }}</label>
        </div>
        <div class="modal-actions">
          <button class="btn" @click="save">{{ t('iconLib.save') }}</button>
          <button class="btn ghost" @click="showForm = false">{{ t('iconLib.cancel') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import ServiceIcon from '../components/ServiceIcon.vue'

const { t } = useI18n()
const loading = ref(true)
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
const job = ref(null)
let pollTimer = null

const activeCount = computed(() => items.value.filter((x) => x.is_active).length)
const inactiveCount = computed(() => items.value.length - activeCount.value)
const cachedCount = computed(() => items.value.filter((x) => x.cached).length)
const missingCount = computed(() => items.value.length - cachedCount.value)
const progressPct = computed(() => job.value?.total ? Math.round((job.value.done / job.value.total) * 100) : 0)

const shown = computed(() => {
  let out = items.value.slice()
  if (activeFilter.value === 'active') out = out.filter((x) => x.is_active)
  if (activeFilter.value === 'inactive') out = out.filter((x) => !x.is_active)
  if (cacheFilter.value === 'cached') out = out.filter((x) => x.cached)
  if (cacheFilter.value === 'missing') out = out.filter((x) => !x.cached)
  if (categoryFilter.value) out = out.filter((x) => x.category === categoryFilter.value)
  const s = q.value.toLowerCase()
  if (s) out = out.filter((x) => x.name.toLowerCase().includes(s) || x.domain.toLowerCase().includes(s) || x.slug.toLowerCase().includes(s))
  return out
})

function blank() {
  return { name: '', domain: '', website: '', category: categories.value[0]?.key || 'other', slug: '', is_active: true, sort: 0 }
}

async function load() {
  loading.value = true
  const [svc, cat] = await Promise.all([
    api.get('/api/admin/icon-services'),
    api.get('/api/admin/icon-services/categories')
  ])
  items.value = svc.data
  categories.value = cat.data
  loading.value = false
}

function openNew() { editing.value = null; formErr.value = ''; form.value = blank(); showForm.value = true }
function openEdit(svc) { editing.value = svc; formErr.value = ''; form.value = { ...svc }; showForm.value = true }
function duplicate(svc) {
  editing.value = null
  formErr.value = ''
  form.value = {
    name: `${svc.name} (${t('iconLib.copySuffix')})`,
    domain: svc.domain,
    website: svc.website || '',
    category: svc.category,
    slug: '',
    is_active: true,
    sort: svc.sort || 0
  }
  showForm.value = true
}

async function save() {
  if (!form.value.name) return (formErr.value = t('iconLib.nameReq'))
  if (!form.value.domain) return (formErr.value = t('iconLib.domainReq'))
  const payload = { ...form.value, website: form.value.website || null, slug: form.value.slug || null }
  try {
    if (editing.value) await api.patch(`/api/admin/icon-services/${editing.value.id}`, payload)
    else await api.post('/api/admin/icon-services', payload)
    showForm.value = false
    await load()
  } catch (e) {
    formErr.value = e?.response?.data?.detail || String(e)
  }
}

async function deactivate(svc) {
  if (!confirm(t('iconLib.confirmDeactivate'))) return
  await api.delete(`/api/admin/icon-services/${svc.id}`)
  await load()
}
async function restore(svc) { await api.post(`/api/admin/icon-services/${svc.id}/restore`); await load() }
async function fetchOne(svc) { await api.post(`/api/admin/icon-services/${svc.id}/prewarm`, null, { params: { force: true } }); await load() }

async function startPrewarm(mode, force = false) {
  if (mode === 'all' && !confirm(t('iconLib.confirmFetchAll'))) return
  const { data } = await api.post('/api/admin/icon-services/prewarm', { mode, force })
  job.value = data
  startPoll(data.id)
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
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:16px; }
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
.seg { display:inline-flex; padding:3px; border-radius:10px; background:var(--surface-2); border:1px solid var(--border); }
.seg button { border:none; background:transparent; color:var(--text-soft); padding:6px 10px; border-radius:8px; cursor:pointer; }
.seg button.on { background:var(--primary); color:#fff; }
.search { max-width:280px; }
.table-card { overflow:auto; }
.svc-ico { width:30px; height:30px; border-radius:8px; border:1px solid var(--border); object-fit:contain; background:var(--surface-2); }
.small { font-size:12px; }
.acts { display:flex; gap:6px; flex-wrap:wrap; }
.tag.ok, .tag.success { background:#dcfce7; color:#166534; }
.tag.off, .tag.failed { background:#fee2e2; color:#991b1b; }
.tag.skipped { background:#fef3c7; color:#92400e; }
.tag.running { background:var(--primary-soft); color:var(--primary); }
.modal label { display:block; margin-top:10px; font-size:13px; font-weight:600; }
.check { display:flex !important; align-items:center; gap:6px; margin-top:26px !important; }
.check input { width:auto; }
.modal-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:16px; }
@media (max-width: 900px) { .stats { grid-template-columns: repeat(2, 1fr); } .head { flex-direction:column; } }
@media (max-width: 720px) { table { min-width: 820px; } }
</style>
