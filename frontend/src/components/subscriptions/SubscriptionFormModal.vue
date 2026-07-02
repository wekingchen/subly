<template>
  <div class="modal-mask">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="subscription-form-title">
      <button type="button" class="modal-x" :aria-label="t('common.close')" @click="emit('close')">×</button>
      <h3 id="subscription-form-title">{{ form.id ? t('sub.edit') : t('sub.add') }}</h3>

      <div class="block">
        <div class="block-t">{{ t('sub.secService') }}</div>
        <div class="row">
          <div class="icon-pick">
            <ServiceIcon :src="form.icon" :name="form.name" :fallback="form.icon || '🔖'" class="ico-lg" />
          </div>
          <div style="flex:2;position:relative">
            <label>{{ t('sub.name') }}</label>
            <input v-model="form.name" @input="onNameInput" autocomplete="off" />
            <div v-if="suggestions.length" class="suggest">
              <button type="button" v-for="s in suggestions" :key="s.slug" class="suggest-i" @click="pickService(s)">
                <ServiceIcon :src="s.icon" :name="s.name" class="ico" loading="lazy" decoding="async" /> {{ s.name }}
              </button>
            </div>
          </div>
          <div style="flex:1">
            <label>{{ t('sub.plan') }}</label>
            <input v-model="form.plan" :placeholder="t('sub.planPh')" />
          </div>
        </div>
        <label>{{ t('sub.remark') }}</label>
        <input v-model="form.remark" :placeholder="t('sub.remarkPh')" />

        <!-- VPS：IP 地址（选填） -->
        <template v-if="isVpsCategory">
          <label>{{ t('sub.ipLabel') }}</label>
          <div class="row">
            <div style="flex:1">
              <input v-model="form.ipv4" :placeholder="t('sub.ipv4')" />
            </div>
            <div style="flex:1">
              <input v-model="form.ipv6" :placeholder="t('sub.ipv6')" />
            </div>
          </div>
        </template>

        <button type="button" class="btn ghost sm" style="margin-top:8px" @click="openBrowser">📚 {{ t('sub.browse') }}</button>

        <details class="icon-lib" @toggle="onIconLibraryToggle">
          <summary>{{ t('sub.icon') }} — {{ t('sub.iconLibrary') }} / URL / {{ t('sub.uploadIcon') }}</summary>
          <input v-model="form.icon" placeholder="🔖 emoji / /static/... / https://..." style="margin:8px 0" />
          <div class="row" style="margin-bottom:8px">
            <input v-model="iconUrl" :placeholder="t('sub.iconUrl')" style="flex:1" />
            <button type="button" class="btn ghost sm" @click="importIconUrl">{{ t('sub.iconUrlImport') }}</button>
            <label class="btn ghost sm" style="width:auto">{{ t('sub.uploadIcon') }}
              <input type="file" accept="image/*" hidden @change="uploadIcon" />
            </label>
          </div>
          <div v-if="showIconLibrary" class="lib-grid">
            <button type="button" v-for="it in visibleIconLib" :key="it.slug" class="lib-ico-btn" :title="it.name" @click="form.icon = it.icon">
              <ServiceIcon :src="it.icon" :name="it.name" class="lib-ico" loading="lazy" decoding="async" />
            </button>
          </div>
          <div v-if="showIconLibrary && visibleIconLib.length < iconLibrary.length" class="row" style="justify-content:center;margin-top:8px">
            <button type="button" class="btn ghost sm" @click="showMoreIcons">{{ t('sub.moreIcons') }}</button>
          </div>
        </details>
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secPrice') }}</div>
        <div class="row">
          <div style="flex:1">
            <label>{{ t('sub.amount') }}</label>
            <input v-model.number="form.amount" type="number" step="0.01" />
          </div>
          <div style="flex:1">
            <label>{{ t('sub.currency') }}</label>
            <select v-model="form.currency">
              <option v-for="c in currencies" :key="c.code" :value="c.code">{{ c.code }} {{ c.symbol }}</option>
            </select>
          </div>
        </div>
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secBilling') }}</div>
        <div class="row">
          <div style="flex:1">
            <label>{{ t('sub.billingType') }}</label>
            <select v-model="form.billing_type">
              <option value="recurring">{{ t('sub.recurring') }}</option>
              <option value="one_time">{{ t('sub.oneTime') }}</option>
            </select>
          </div>
          <template v-if="form.billing_type === 'recurring'">
            <div style="flex:1">
              <label>{{ t('sub.cycleCount') }}</label>
              <input v-model.number="form.cycle_count" type="number" min="1" />
            </div>
            <div style="flex:1">
              <label>{{ t('sub.cycle') }}</label>
              <select v-model="form.cycle">
                <option value="day">{{ t('sub.day') }}</option>
                <option value="week">{{ t('sub.week') }}</option>
                <option value="month">{{ t('sub.month') }}</option>
                <option value="year">{{ t('sub.year') }}</option>
              </select>
            </div>
          </template>
        </div>
        <div class="row">
          <div style="flex:1">
            <label>{{ t('sub.startDate') }}</label>
            <input v-model="form.start_date" type="date" />
          </div>
          <div style="flex:1" v-if="form.billing_type === 'recurring'">
            <label>{{ t('sub.nextRenewal') }} <span class="auto-tip">· 自动</span></label>
            <input v-model="form.next_renewal_date" type="date" />
          </div>
        </div>
        <div class="row" v-if="form.billing_type === 'recurring'">
          <div style="flex:1">
            <label>{{ t('sub.remindDays') }}</label>
            <input v-model="form.remind_days_before" placeholder="7,1" />
          </div>
          <div style="flex:1">
            <label>{{ t('sub.active') }}</label>
            <select v-model="form.is_active"><option :value="true">✓</option><option :value="false">✗</option></select>
          </div>
          <div style="flex:1">
            <label>{{ t('sub.autoRenew') }}</label>
            <select v-model="form.auto_renew"><option :value="true">✓</option><option :value="false">✗</option></select>
          </div>
        </div>
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secClassify') }}</div>
        <div class="row">
          <div style="flex:1">
            <label>{{ t('sub.category') }}</label>
            <select v-model="form.category_id">
              <option :value="null">—</option>
              <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.icon }} {{ c.name }}</option>
            </select>
          </div>
          <div style="flex:1">
            <label>{{ t('sub.payment') }}</label>
            <select v-model="form.payment_method_id">
              <option :value="null">—</option>
              <option v-for="p in methods" :key="p.id" :value="p.id">{{ p.icon }} {{ p.name }}</option>
            </select>
          </div>
        </div>
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secFamily') }}</div>
        <div class="chips">
          <span v-for="(m, i) in form.family_members" :key="i" class="chip">
            {{ m }} <a href="#" @click.prevent="removeMember(i)">✕</a>
          </span>
        </div>
        <div class="row">
          <input v-model="newMember" :placeholder="t('sub.familyPh')" @keyup.enter="addMember" style="flex:1" />
          <button type="button" class="btn ghost sm" @click="addMember">{{ t('sub.familyAdd') }}</button>
        </div>
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secBundle') }}</div>
        <div class="row radio-row">
          <label class="rb"><input type="radio" value="none" v-model="bundleMode" /> {{ t('sub.bundleNone') }}</label>
          <label class="rb"><input type="radio" value="join" v-model="bundleMode" /> {{ t('sub.bundleJoin') }}</label>
          <label class="rb"><input type="radio" value="create" v-model="bundleMode" /> {{ t('sub.bundleCreate') }}</label>
        </div>
        <select v-if="bundleMode === 'join'" v-model="form.bundle_id">
          <option :value="null">—</option>
          <option v-for="b in bundles" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>
        <input v-if="bundleMode === 'create'" v-model="newBundleName" :placeholder="t('sub.bundleName')" />
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secExtra') }}</div>
        <label>{{ t('sub.website') }}</label>
        <input v-model="form.url" placeholder="https://..." />
        <label>{{ t('sub.notes') }}</label>
        <textarea v-model="form.notes" rows="2"></textarea>
      </div>

      <div class="block">
        <div class="block-t">{{ t('sub.secCalendar') }}</div>
        <label class="rb"><input type="checkbox" v-model="form.show_in_calendar" /> {{ t('sub.showInCalendar') }}</label>
      </div>

      <p v-if="formErr" class="err">{{ formErr }}</p>
      <div class="modal-foot">
        <button type="button" class="btn ghost" @click="emit('close')">{{ t('sub.cancel') }}</button>
        <button type="button" class="btn" @click="save">{{ t('sub.save') }}</button>
      </div>
    </div>
  </div>

  <ServiceBrowserModal
    v-if="showBrowser"
    :services="iconLibrary"
    @close="showBrowser = false"
    @pick="pickFromBrowser"
  />
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import ServiceIcon from '../ServiceIcon.vue'
import ServiceBrowserModal from './ServiceBrowserModal.vue'
import { buildServicePickPatch, isVpsCategory as isVpsServiceCategory, suggestServicesByName } from '../../utils/serviceLibrary'
import { buildSubscriptionPayload, cloneSubscriptionForEdit, computeNextRenewalDate, createBlankSubscriptionForm } from '../../utils/subscriptionForm'

const props = defineProps({
  subscription: { type: Object, default: null },
  currencies: { type: Array, default: () => [] },
  categories: { type: Array, default: () => [] },
  methods: { type: Array, default: () => [] },
  bundles: { type: Array, default: () => [] },
  iconLibrary: { type: Array, default: () => [] }
})

const emit = defineEmits(['close', 'saved', 'bundle-created'])
const { t } = useI18n()

const form = ref({})
const formErr = ref('')
const newMember = ref('')
const iconUrl = ref('')
const bundleMode = ref('none')
const newBundleName = ref('')
const suggestions = ref([])
const showIconLibrary = ref(false)
const visibleIconCount = ref(0)
const showBrowser = ref(false)
const ICON_BATCH_SIZE = 18
let suppressAuto = false

const visibleIconLib = computed(() => props.iconLibrary.slice(0, visibleIconCount.value))
const isVpsCategory = computed(() => {
  const c = props.categories.find((x) => x.id === form.value.category_id)
  return isVpsServiceCategory(c)
})

function resetTransientState() {
  formErr.value = ''
  newMember.value = ''
  iconUrl.value = ''
  newBundleName.value = ''
  suggestions.value = []
  showIconLibrary.value = false
  visibleIconCount.value = 0
  showBrowser.value = false
}

function recomputeNext() {
  form.value.next_renewal_date = computeNextRenewalDate(form.value, form.value.next_renewal_date)
}

function initializeForm(subscription) {
  resetTransientState()
  if (subscription) {
    suppressAuto = true
    form.value = cloneSubscriptionForEdit(subscription)
    bundleMode.value = subscription.bundle_id ? 'join' : 'none'
    nextTick(() => { suppressAuto = false })
    return
  }
  suppressAuto = false
  form.value = createBlankSubscriptionForm()
  bundleMode.value = 'none'
  recomputeNext()
}

watch(() => props.subscription, initializeForm, { immediate: true })

watch(
  () => [form.value.start_date, form.value.cycle, form.value.cycle_count, form.value.billing_type],
  () => { if (!suppressAuto) recomputeNext() }
)

function onIconLibraryToggle(e) {
  showIconLibrary.value = e.target.open
  visibleIconCount.value = e.target.open ? ICON_BATCH_SIZE : 0
}

function showMoreIcons() {
  visibleIconCount.value = Math.min(props.iconLibrary.length, visibleIconCount.value + ICON_BATCH_SIZE)
}

function onNameInput() {
  suggestions.value = suggestServicesByName(props.iconLibrary, form.value.name, 6)
}

function pickService(s) {
  Object.assign(form.value, buildServicePickPatch(form.value, s, props.categories))
  suggestions.value = []
}

function openBrowser() {
  showBrowser.value = true
}

function pickFromBrowser(s) {
  pickService(s)
  showBrowser.value = false
}

function addMember() {
  const v = newMember.value.trim()
  if (v) {
    form.value.family_members.push(v)
    newMember.value = ''
  }
}

function removeMember(index) {
  form.value.family_members.splice(index, 1)
}

async function importIconUrl() {
  if (!iconUrl.value.trim()) return
  try {
    const { data } = await api.post('/api/icons/from-url', { url: iconUrl.value.trim() })
    form.value.icon = data.url
    iconUrl.value = ''
  } catch (e) {
    formErr.value = e.response?.data?.detail || 'Error'
  }
}

async function uploadIcon(e) {
  const file = e.target.files[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await api.post('/api/icons/upload', fd)
  form.value.icon = data.url
}

async function save() {
  formErr.value = ''
  try {
    if (bundleMode.value === 'create' && newBundleName.value.trim()) {
      const { data } = await api.post('/api/bundles', { name: newBundleName.value.trim() })
      form.value.bundle_id = data.id
      bundleMode.value = 'join'
      newBundleName.value = ''
      emit('bundle-created', data)
    } else if (bundleMode.value === 'none') {
      form.value.bundle_id = null
    }
    const payload = buildSubscriptionPayload(form.value)
    if (payload.id) await api.put(`/api/subscriptions/${payload.id}`, payload)
    else await api.post('/api/subscriptions', payload)
    emit('saved')
  } catch (e) {
    formErr.value = e.response?.data?.detail || 'Error'
  }
}
</script>

<style scoped>
.err { color: var(--danger); font-size: 13px; }
.ico { width: 18px; height: 18px; vertical-align: middle; border-radius: 4px; }
.auto-tip { color: var(--primary); font-size: 11px; }
.block { border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 12px; }
.block-t { font-size: 13px; font-weight: 600; color: var(--primary); margin-bottom: 6px; }
.icon-pick { display: flex; align-items: flex-end; }
.ico-lg { width: 40px; height: 40px; border-radius: 8px; object-fit: contain; border: 1px solid var(--border); }
.ico-lg.emoji { display: flex; align-items: center; justify-content: center; font-size: 24px; }
.suggest { position: absolute; z-index: 5; left: 0; right: 0; background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow); margin-top: 2px; }
.suggest-i { display: flex; align-items: center; gap: 8px; padding: 7px 10px; cursor: pointer; font-size: 14px;
  width: 100%; background: transparent; border: none; text-align: left; color: var(--text); }
.suggest-i:hover { background: var(--primary-soft); }
.icon-lib summary { cursor: pointer; font-size: 13px; color: var(--text-soft); }
.lib-grid { display: grid; grid-template-columns: repeat(auto-fill, 34px); gap: 8px; max-height: 140px; overflow: auto; }
.lib-ico-btn { width: 34px; height: 34px; padding: 0; border: none; background: transparent; cursor: pointer; }
.lib-ico { width: 30px; height: 30px; border-radius: 6px; padding: 3px; border: 1px solid var(--border); object-fit: contain; }
.lib-ico-btn:hover .lib-ico { border-color: var(--primary); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chip { background: var(--primary-soft); color: var(--primary); padding: 3px 8px; border-radius: 16px; font-size: 13px; }
.radio-row { gap: 18px; }
.rb { display: flex; align-items: center; gap: 6px; width: auto; margin: 0; font-size: 14px; color: var(--text); }
.rb input { width: auto; }
@media (max-width: 720px) {
  .block { padding: 10px; margin-bottom: 10px; background: color-mix(in srgb, var(--surface-2) 42%, transparent); }
  .block-t { margin-bottom: 8px; }
  .icon-pick { width: 100%; justify-content: center; align-items: center; }
  .ico-lg { width: 56px; height: 56px; }
  .radio-row { display: grid; grid-template-columns: 1fr; gap: 8px; }
  .rb { min-height: 44px; align-items: center; }
  .chips { gap: 8px; }
  .chip { max-width: 100%; overflow-wrap: anywhere; }
  .lib-grid { grid-template-columns: repeat(auto-fill, minmax(44px, 1fr)); max-height: 190px; }
  .lib-ico-btn { width: 44px; height: 44px; justify-self: center; }
}
</style>
