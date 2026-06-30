<template>
  <div>
    <div class="head">
      <h1>{{ t('admin.title') }}</h1>
      <button class="btn" @click="openNew">+ {{ t('admin.createUser') }}</button>
    </div>

    <div class="seg">
      <button :class="{ on: tab === 'pending' }" @click="tab = 'pending'">
        {{ t('admin.pendingTab', { n: pendingUsers.length }) }}
      </button>
      <button :class="{ on: tab === 'all' }" @click="tab = 'all'">{{ t('admin.allTab') }}</button>
    </div>

    <div class="card">
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
          <tr v-for="u in shown" :key="u.id">
            <td :data-label="t('admin.username')">{{ u.username }}</td>
            <td :data-label="t('admin.email')" class="muted">
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
            <td :data-label="t('admin.subs')">{{ u.subscription_count }}</td>
            <td :data-label="t('admin.created')" class="muted">{{ fmt(u.created_at) }}</td>
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
          <tr v-if="!shown.length">
            <td colspan="7" class="muted" style="text-align:center">
              {{ tab === 'pending' ? t('admin.noPending') : t('reports.empty') }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="err" class="err">{{ err }}</p>
    </div>

    <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
      <div class="modal" style="width:420px">
        <button class="modal-x" :aria-label="t('common.close')" @click="showForm = false">×</button>
        <h3>{{ t('admin.createUser') }}</h3>
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
        <div class="modal-foot">
          <button class="btn ghost" @click="showForm = false">{{ t('admin.cancel') }}</button>
          <button class="btn" @click="create">{{ t('admin.create') }}</button>
        </div>
      </div>
    </div>

    <div v-if="pwdTarget" class="modal-mask" @click.self="pwdTarget = null">
      <div class="modal" style="width:420px">
        <button class="modal-x" :aria-label="t('common.close')" @click="pwdTarget = null">×</button>
        <h3>{{ t('admin.resetPwd') }}</h3>
        <p style="font-size:14px;line-height:1.6">{{ t('admin.resetPwdPrompt') }} · {{ pwdTarget.username }}</p>
        <input v-model="pwdValue" type="password" :placeholder="t('admin.newPwdPh')" @keyup.enter="confirmResetPwd" />
        <div class="modal-foot">
          <button class="btn ghost" @click="pwdTarget = null">{{ t('admin.cancel') }}</button>
          <button class="btn" :disabled="!pwdValue" @click="confirmResetPwd">{{ t('common.confirm') }}</button>
        </div>
      </div>
    </div>

    <div v-if="delTarget" class="modal-mask" @click.self="delTarget = null">
      <div class="modal" style="width:420px">
        <button class="modal-x" :aria-label="t('common.close')" @click="delTarget = null">×</button>
        <h3>🗑️ {{ t('admin.deleteTitle') }}</h3>
        <p style="font-size:14px;line-height:1.6">{{ t('admin.confirmDelete') }} · {{ delTarget.username }}</p>
        <div class="modal-foot">
          <button class="btn ghost" @click="delTarget = null">{{ t('admin.cancel') }}</button>
          <button class="btn danger" @click="confirmDelete">{{ t('common.confirm') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'

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

watch([showForm, pwdTarget, delTarget], () => {
  const open = showForm.value || pwdTarget.value || delTarget.value
  document.body.classList.toggle('modal-open', !!open)
})
onBeforeUnmount(() => document.body.classList.remove('modal-open'))

function fmt(s) { return s ? new Date(s).toLocaleDateString() : '' }

const pendingUsers = computed(() => users.value.filter((u) => !u.is_approved))
const shown = computed(() => (tab.value === 'pending' ? pendingUsers.value : users.value))

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
h1 { margin-top: 0; }
.seg { margin-bottom: 14px; }
.acts { display: flex; gap: 6px; flex-wrap: wrap; }
.err { color: var(--danger); font-size: 13px; }
.tag.adm { background: #ede9fe; color: #6d28d9; }
.tag.ok { background: #dcfce7; color: #15803d; }
.tag.bad { background: #fee2e2; color: #b91c1c; }
.tag.warn { background: #fef3c7; color: #b45309; }
.tag.sm { padding: 1px 6px; font-size: 11px; margin-left: 4px; }
.rb { display: flex; align-items: center; gap: 6px; width: auto; margin: 0; }
.rb input { width: auto; }
@media (max-width: 720px) {
  table, thead, tbody, th, td, tr { display: block; }
  thead { display: none; }
  tr { border: 1px solid var(--border); border-radius: 10px; padding: 8px; margin-bottom: 10px; }
  td { border: none; padding: 6px 6px 4px; }
  td::before { content: attr(data-label); display: block; font-size: 11px; font-weight: 600;
    color: var(--text-soft); text-transform: uppercase; letter-spacing: .03em; margin-bottom: 2px; }
  td.acts::before { display: none; }
  .acts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .acts .btn.sm { min-height: 44px; }
  .acts .btn.danger { grid-column: 1 / -1; }
}
</style>
