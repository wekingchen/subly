<template>
  <div class="users-page">
    <section class="users-hero card radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span> 成员矩阵</div>
        <h1>{{ t('admin.title') }}</h1>
        <p class="muted">审核注册、分配权限、处理账号状态，让成员访问保持在可控范围内。</p>
      </div>
      <div class="hero-actions">
        <button class="btn" @click="openNew">+ {{ t('admin.createUser') }}</button>
      </div>
      <div class="user-metrics">
        <div class="metric-card">
          <span>{{ t('admin.allTab') }}</span>
          <b class="mono-data">{{ users.length }}</b>
        </div>
        <div class="metric-card warn">
          <span>{{ t('admin.pending') }}</span>
          <b class="mono-data">{{ pendingUsers.length }}</b>
        </div>
        <div class="metric-card">
          <span>{{ t('admin.admin') }}</span>
          <b class="mono-data">{{ adminCount }}</b>
        </div>
        <div class="metric-card bad">
          <span>{{ t('admin.disabled') }}</span>
          <b class="mono-data">{{ disabledCount }}</b>
        </div>
      </div>
    </section>

    <div class="toolbar-row">
      <div class="seg">
        <button :class="{ on: tab === 'pending' }" @click="tab = 'pending'">
          {{ t('admin.pendingTab', { n: pendingUsers.length }) }}
        </button>
        <button :class="{ on: tab === 'all' }" @click="tab = 'all'">{{ t('admin.allTab') }}</button>
      </div>
    </div>

    <div class="card user-panel">
      <div class="panel-head">
        <div>
          <div class="panel-title"><span class="panel-signal"></span>{{ tab === 'pending' ? t('admin.pending') : t('admin.allTab') }}</div>
          <p class="muted">共 {{ shown.length }} 个成员信号，操作会实时同步到账号权限。</p>
        </div>
      </div>
      <div class="user-table-wrap">
        <table>
          <thead>
            <tr>
              <th>{{ t('admin.username') }}</th>
              <th>{{ t('admin.email') }}</th>
              <th>{{ t('admin.role') }}</th>
              <th>{{ t('admin.status') }}</th>
              <th>{{ t('admin.subs') }}</th>
              <th>{{ t('admin.created') }}</th>
              <th>{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in shown" :key="u.id" :class="{ pending: !u.is_approved, disabled: !u.is_active }">
              <td :data-label="t('admin.username')">
                <div class="user-cell">
                  <span class="avatar">{{ initials(u.username) }}</span>
                  <b>{{ u.username }}</b>
                </div>
              </td>
              <td :data-label="t('admin.email')" class="muted email-cell">
                {{ u.email }}
                <span v-if="!u.email_verified" class="tag bad sm" :title="t('admin.emailUnverified')">✉︎!</span>
              </td>
              <td :data-label="t('admin.role')">
                <span class="tag" :class="u.is_admin ? 'adm' : ''">
                  {{ u.is_admin ? t('admin.admin') : t('admin.user') }}
                </span>
              </td>
              <td :data-label="t('admin.status')">
                <span v-if="!u.is_approved" class="tag warn">{{ t('admin.pending') }}</span>
                <span v-else class="tag" :class="u.is_active ? 'ok' : 'bad'">
                  {{ u.is_active ? t('admin.active') : t('admin.disabled') }}
                </span>
              </td>
              <td :data-label="t('admin.subs')" class="mono-data">{{ u.subscription_count }}</td>
              <td :data-label="t('admin.created')" class="muted mono-data">{{ fmt(u.created_at) }}</td>
              <td class="acts" :data-label="t('common.actions')">
                <button v-if="!u.is_approved" class="btn sm" @click="approve(u)">✓ {{ t('admin.approve') }}</button>
                <button class="btn sm ghost" @click="toggleAdmin(u)">
                  {{ u.is_admin ? t('admin.revokeAdmin') : t('admin.makeAdmin') }}
                </button>
                <button class="btn sm ghost" @click="toggleActive(u)">
                  {{ u.is_active ? t('admin.disable') : t('admin.enable') }}
                </button>
                <button class="btn sm ghost" @click="resetPwd(u)">{{ t('admin.resetPwd') }}</button>
                <button class="btn sm danger" @click="remove(u)">{{ t('sub.delete') }}</button>
              </td>
            </tr>
            <tr v-if="!shown.length" class="empty-row">
              <td colspan="7" class="muted">
                {{ tab === 'pending' ? t('admin.noPending') : t('reports.empty') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="err" class="err">{{ err }}</p>
    </div>

    <AppModal v-model="showForm" :title="t('admin.createUser')" width="420px" :close-label="t('common.close')">
      <label>{{ t('admin.username') }}</label>
      <input v-model="form.username" />
      <label>{{ t('admin.email') }}</label>
      <input v-model="form.email" type="email" />
      <label>{{ t('admin.password') }}</label>
      <input v-model="form.password" type="password" />
      <label class="rb" style="margin-top:10px">
        <input type="checkbox" v-model="form.is_admin" /> {{ t('admin.admin') }}
      </label>
      <p v-if="formErr" class="err">{{ formErr }}</p>
      <template #footer>
        <button class="btn ghost" @click="showForm = false">{{ t('admin.cancel') }}</button>
        <button class="btn" @click="create">{{ t('admin.create') }}</button>
      </template>
    </AppModal>

    <AppModal v-model="pwdOpen" :title="t('admin.resetPwd')" width="420px" :close-label="t('common.close')">
      <p class="modal-copy">{{ t('admin.resetPwdPrompt') }} · {{ pwdTarget?.username }}</p>
      <input v-model="pwdValue" type="password" :placeholder="t('admin.newPwdPh')" @keyup.enter="confirmResetPwd" />
      <template #footer>
        <button class="btn ghost" @click="pwdTarget = null">{{ t('admin.cancel') }}</button>
        <button class="btn" :disabled="!pwdValue" @click="confirmResetPwd">{{ t('common.confirm') }}</button>
      </template>
    </AppModal>

    <AppModal v-model="delOpen" :title="t('admin.deleteTitle')" width="420px" :close-label="t('common.close')">
      <p class="modal-copy">{{ t('admin.confirmDelete') }} · {{ delTarget?.username }}</p>
      <template #footer>
        <button class="btn ghost" @click="delTarget = null">{{ t('admin.cancel') }}</button>
        <button class="btn danger" @click="confirmDelete">{{ t('common.confirm') }}</button>
      </template>
    </AppModal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import AppModal from '../components/AppModal.vue'

const { t } = useI18n()
const users = ref([])
const err = ref('')
const tab = ref('pending')
const showForm = ref(false)
const formErr = ref('')
const form = ref({ username: '', email: '', password: '', is_admin: false })

const pwdTarget = ref(null)
const pwdValue = ref('')
const delTarget = ref(null)
const pwdOpen = computed({
  get: () => pwdTarget.value !== null,
  set: (v) => { if (!v) pwdTarget.value = null }
})
const delOpen = computed({
  get: () => delTarget.value !== null,
  set: (v) => { if (!v) delTarget.value = null }
})

function fmt(s) { return s ? new Date(s).toLocaleDateString() : '' }
function initials(name) { return String(name || '?').trim().slice(0, 1).toUpperCase() || '?' }

const pendingUsers = computed(() => users.value.filter((u) => !u.is_approved))
const shown = computed(() => (tab.value === 'pending' ? pendingUsers.value : users.value))
const adminCount = computed(() => users.value.filter((u) => u.is_admin).length)
const disabledCount = computed(() => users.value.filter((u) => !u.is_active).length)

async function load() {
  err.value = ''
  try {
    users.value = (await api.get('/api/admin/users')).data
    // 没有待审核用户时默认展示全部，避免空白
    if (tab.value === 'pending' && !pendingUsers.value.length) tab.value = 'all'
  } catch (e) { err.value = e.response?.data?.detail || 'Error' }
}

function openNew() {
  form.value = { username: '', email: '', password: '', is_admin: false }
  formErr.value = ''; showForm.value = true
}
async function create() {
  formErr.value = ''
  try {
    await api.post('/api/admin/users', form.value)
    showForm.value = false; load()
  } catch (e) { formErr.value = e.response?.data?.detail || 'Error' }
}

async function patch(u, body) {
  err.value = ''
  try { await api.patch(`/api/admin/users/${u.id}`, body); load() }
  catch (e) { err.value = e.response?.data?.detail || 'Error' }
}
const approve = (u) => patch(u, { is_approved: true })
const toggleAdmin = (u) => patch(u, { is_admin: !u.is_admin })
const toggleActive = (u) => patch(u, { is_active: !u.is_active })
function resetPwd(u) {
  pwdTarget.value = u
  pwdValue.value = ''
}
async function confirmResetPwd() {
  if (!pwdTarget.value || !pwdValue.value) return
  await patch(pwdTarget.value, { password: pwdValue.value })
  pwdTarget.value = null
  pwdValue.value = ''
}
function remove(u) {
  delTarget.value = u
}
async function confirmDelete() {
  if (!delTarget.value) return
  err.value = ''
  const id = delTarget.value.id
  try { await api.delete(`/api/admin/users/${id}`); delTarget.value = null; load() }
  catch (e) { err.value = e.response?.data?.detail || 'Error' }
}

onMounted(load)
</script>

<style scoped>
.users-page { display: flex; flex-direction: column; gap: 16px; }
.users-hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: start;
  background: linear-gradient(135deg, color-mix(in srgb, var(--surface) 88%, var(--radar-panel)), var(--surface)); }
.users-hero > * { position: relative; z-index: 1; }
.hero-kicker { display: flex; align-items: center; gap: 8px; color: var(--text-soft); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 8px 0; }
.hero-copy p { margin: 0; line-height: 1.7; max-width: 660px; }
.hero-actions { display: flex; justify-content: flex-end; }
.user-metrics { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }
.metric-card { padding: 12px; border-radius: 14px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface-2) 82%, transparent); }
.metric-card span { display: block; color: var(--text-soft); font-size: 12px; margin-bottom: 5px; }
.metric-card b { font-size: 18px; }
.metric-card.warn { border-color: color-mix(in srgb, var(--warning) 30%, var(--border)); }
.metric-card.bad { border-color: color-mix(in srgb, var(--danger) 30%, var(--border)); }
.toolbar-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.user-panel { padding: 0; overflow: hidden; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 18px 20px 4px; }
.panel-head p { margin: 5px 0 0; font-size: 13px; }
.panel-title { display: flex; align-items: center; gap: 9px; font-size: 16px; font-weight: 850; letter-spacing: -.02em; }
.panel-signal { width: 9px; height: 9px; border-radius: 999px; background: var(--signal-cyan);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--signal-cyan) 13%, transparent), 0 0 18px color-mix(in srgb, var(--signal-cyan) 45%, transparent); }
.user-table-wrap { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; padding: 0 10px 10px; }
.user-table-wrap table { min-width: 780px; }
tbody tr { transition: background .15s ease; }
tbody tr:hover { background: color-mix(in srgb, var(--primary) 5%, transparent); }
tbody tr.pending { background: color-mix(in srgb, var(--warning) 5%, transparent); }
tbody tr.disabled { opacity: .76; }
.user-cell { display: flex; align-items: center; gap: 9px; }
.avatar { width: 30px; height: 30px; border-radius: 10px; display: inline-flex; align-items: center; justify-content: center;
  background: color-mix(in srgb, var(--signal-cyan) 15%, var(--surface-2)); color: var(--primary); border: 1px solid color-mix(in srgb, var(--signal-cyan) 32%, var(--border)); font-weight: 900; }
.email-cell { word-break: break-word; }
.acts { display: flex; gap: 6px; flex-wrap: wrap; }
.err { color: var(--danger); font-size: 13px; padding: 0 20px 18px; }
.tag.adm { background: color-mix(in srgb, #8b5cf6 17%, transparent); color: #8b5cf6; }
.tag.ok { background: color-mix(in srgb, var(--success) 16%, transparent); color: var(--success); }
.tag.bad { background: color-mix(in srgb, var(--danger) 18%, transparent); color: var(--danger); }
.tag.warn { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.tag.sm { padding: 1px 6px; font-size: 11px; margin-left: 4px; }
.empty-row td { text-align: center; padding: 24px 10px; }
.rb { display: flex; align-items: center; gap: 6px; width: auto; margin: 0; }
.rb input { width: auto; }
.modal-copy { font-size: 14px; line-height: 1.6; }
@media (max-width: 900px) {
  .users-hero { grid-template-columns: 1fr; }
  .hero-actions .btn { width: 100%; }
  .user-metrics { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 720px) {
  .user-metrics { grid-template-columns: 1fr; }
  .toolbar-row .seg { width: 100%; }
  .toolbar-row .seg button { flex: 1; }
  .user-panel { padding: 0 0 6px; }
  .panel-head { padding: 16px 16px 0; }
  .user-table-wrap { padding: 0 12px 10px; overflow: visible; }
  .user-table-wrap table { min-width: 0; }
  table, thead, tbody, th, td, tr { display: block; }
  thead { display: none; }
  tr { border: 1px solid var(--border); border-left: 4px solid var(--signal-cyan); border-radius: 12px; padding: 8px; margin-bottom: 10px; background: var(--surface); }
  tr.pending { border-left-color: var(--warning); }
  tr.disabled { border-left-color: var(--danger); opacity: 1; }
  td { border: none; padding: 6px 6px 4px; }
  td::before { content: attr(data-label); display: block; font-size: 11px; font-weight: 700;
    color: var(--text-soft); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 2px; }
  td.acts::before { display: none; }
  .acts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .acts .btn.sm { min-height: 44px; }
  .acts .btn.danger { grid-column: 1 / -1; }
  .empty-row { border-left-color: var(--border); }
}
</style>
