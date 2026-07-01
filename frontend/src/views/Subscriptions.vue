<template>
  <div>
    <div class="head">
      <h1>{{ t('nav.subscriptions') }}</h1>
      <button class="btn" @click="openNew">+ {{ t('sub.add') }}</button>
    </div>

    <div class="bar">
      <div class="seg">
        <button :class="{ on: filter === '' }" @click="setFilter('')">{{ t('sub.filterAll') }}</button>
        <button :class="{ on: filter === 'recurring' }" @click="setFilter('recurring')">{{ t('sub.filterRecurring') }}</button>
        <button :class="{ on: filter === 'one_time' }" @click="setFilter('one_time')">{{ t('sub.filterOneTime') }}</button>
      </div>
      <span v-if="!filter" class="muted drag-hint">⠿ {{ t('sub.dragHint') }}</span>
    </div>

    <div v-if="!subs.length" class="card muted">{{ t('dashboard.none') }}</div>

    <!-- 按分类分组 -->
    <div v-for="g in grouped" :key="g.key" class="cat-group"
         :class="{ 'drop-cat': dragOverCat === g.key }"
         @dragover.prevent="onCatDragOver(g.key)"
         @drop="onCatDrop(g.key)">
      <div class="cat-head"
           :draggable="!filter"
           @dragstart="onCatDragStart(g.key, $event)"
           @dragend="clearDrag">
        <span class="grip">⠿</span>
        <span class="cat-ico">{{ g.icon }}</span>
        <span class="cat-name">{{ g.name }}</span>
        <span class="cat-count">{{ g.items.length }}</span>
        <span v-if="!filter" class="mobile-sort">
          <button class="btn sm ghost" @click.stop="moveCat(g.key, -1)" :aria-label="t('sub.moveUp')">↑</button>
          <button class="btn sm ghost" @click.stop="moveCat(g.key, 1)" :aria-label="t('sub.moveDown')">↓</button>
        </span>
      </div>

      <div class="sub-grid">
        <div v-for="s in g.items" :key="s.id" class="card sub-card signal-card"
             :class="{ inactive: !s.is_active, expired: isExpired(s), soon: isSoon(s), 'drop-card': dragOverSub === s.id, expanded: isExpanded(s.id) }"
             @click="onCardClick(s, $event)"
             @dragover.prevent.stop="onCardDragOver(g.key, s.id)"
             @drop.stop="onCardDrop(g.key, s.id)">
          <div class="status-strip" :class="statusOf(s)"></div>
          <div class="sc-head">
            <ServiceIcon :src="s.icon" :name="s.name" :fallback="s.icon || '🔖'"
                         class="sc-ico" loading="lazy" decoding="async" />
            <div class="sc-title">
              <div class="sc-name">{{ s.name }}</div>
              <div class="muted sc-plan" v-if="s.plan">{{ s.plan }}</div>
            </div>
            <StatusChip :status="statusOf(s)">{{ statusChip(s) }}</StatusChip>
            <button type="button" class="card-detail-toggle" :aria-expanded="isExpanded(s.id)"
                    :aria-controls="detailId(s.id)"
                    :aria-label="`${s.name || t('nav.subscriptions')}：${isExpanded(s.id) ? t('sub.collapse') : t('sub.expand')}`"
                    @click.stop="toggleDetails(s.id)">{{ isExpanded(s.id) ? '▾' : '▸' }}</button>
            <span v-if="!filter" class="card-grip" draggable="true" :title="t('sub.dragCard')" aria-hidden="true"
                  @click.stop
                  @dragstart.stop="onCardDragStart(g.key, s.id, $event)"
                  @dragend="clearDrag">⠿</span>
          </div>

          <div class="sc-signal">
            <div class="sc-amount mono-data">
              <MoneyText :value="s.amount" :currency="s.currency" position="suffix" />
              <span v-if="s.billing_type === 'recurring'" class="muted cycle">/ {{ cycleText(s) }}</span>
            </div>
            <div v-if="shouldShowBaseAmount(s)" class="sc-base-amount">
              <span class="muted">{{ t('sub.baseAmountPrefix') }}</span>
              <MoneyText :value="baseAmount(s)" :currency="baseCurrency" position="prefix" muted />
            </div>

            <div class="sc-due" :class="statusOf(s)" v-if="s.billing_type === 'recurring' && s.next_renewal_date">
              <span class="due mono-data">{{ s.next_renewal_date }}</span>
              <span class="sc-due-text">{{ dueText(s) }}</span>
            </div>
            <div class="sc-due oneTime" v-else-if="s.billing_type === 'one_time'">
              <span class="sc-due-text">{{ t('sub.lifetime') }}</span>
            </div>

            <div v-if="isExpired(s)" class="expired-banner">⚠️ {{ t('sub.expiredTag') }}</div>
            <div v-else-if="isSoon(s)" class="soon-banner">⏰ {{ t('sub.soonTag') }}</div>
          </div>

          <div class="sc-quick">
            <span v-if="payName(s)" class="quick-chip">💳 {{ payName(s) }}</span>
            <span v-if="s.billing_type === 'recurring'" class="quick-chip">🔁 {{ boolText(s.auto_renew) }}</span>
            <span v-if="s.family_members && s.family_members.length" class="quick-chip">👨‍👩‍👧 {{ s.family_members.length }}</span>
            <span v-if="bundleName(s)" class="quick-chip">📦 {{ bundleName(s) }}</span>
          </div>

          <Transition name="detail">
            <div v-if="isExpanded(s.id)" :id="detailId(s.id)" class="sc-detail" @click.stop>
              <div class="detail-section">
                <div class="detail-title">{{ t('sub.detailIdentityCost') }}</div>
                <div class="detail-grid">
                  <div class="detail-item"><div class="detail-label">{{ t('sub.category') }}</div><div class="detail-value">{{ categoryName(s) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.plan') }}</div><div class="detail-value">{{ textOrDash(s.plan) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.originalAmount') }}</div><div class="detail-value mono-data"><MoneyText :value="s.amount" :currency="s.currency" position="suffix" /></div></div>
                  <div v-if="shouldShowBaseAmount(s)" class="detail-item"><div class="detail-label">{{ t('sub.baseCurrencyAmount') }} · {{ baseCurrency }}</div><div class="detail-value mono-data"><MoneyText :value="baseAmount(s)" :currency="baseCurrency" position="suffix" muted /></div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.billingType') }}</div><div class="detail-value">{{ s.billing_type === 'one_time' ? t('sub.oneTime') : t('sub.recurring') }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.cycle') }}</div><div class="detail-value">{{ s.billing_type === 'recurring' ? cycleText(s) : DASH }}</div></div>
                  <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.website') }}</div><div class="detail-value"><a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer" @click.stop>{{ s.url }}</a><span v-else>{{ DASH }}</span></div></div>
                  <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.remark') }}</div><div class="detail-value">{{ textOrDash(s.remark) }}</div></div>
                </div>
              </div>

              <div class="detail-section">
                <div class="detail-title">{{ t('sub.detailRiskReminder') }}</div>
                <div class="detail-grid">
                  <div class="detail-item"><div class="detail-label">{{ t('sub.startDate') }}</div><div class="detail-value mono-data">{{ textOrDash(s.start_date) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.nextRenewal') }}</div><div class="detail-value mono-data">{{ s.billing_type === 'recurring' ? textOrDash(s.next_renewal_date) : t('sub.lifetime') }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.endDate') }}</div><div class="detail-value mono-data">{{ textOrDash(s.end_date) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.lastRenewedAt') }}</div><div class="detail-value mono-data">{{ textOrDash(s.last_renewed_at) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.remindDays') }}</div><div class="detail-value mono-data">{{ textOrDash(s.remind_days_before) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.autoRenew') }}</div><div class="detail-value">{{ boolText(s.auto_renew) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.calendarVisible') }}</div><div class="detail-value">{{ boolText(s.show_in_calendar) }}</div></div>
                </div>
              </div>

              <div class="detail-section">
                <div class="detail-title">{{ t('sub.detailAccountingOwner') }}</div>
                <div class="detail-grid">
                  <div class="detail-item"><div class="detail-label">{{ t('sub.payment') }}</div><div class="detail-value">{{ payName(s) || DASH }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.bundle') }}</div><div class="detail-value">{{ bundleName(s) || DASH }}</div></div>
                  <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.family') }}</div><div class="detail-value">{{ familyText(s) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.ipv4') }}</div><div class="detail-value mono-data">{{ textOrDash(s.ipv4) }}</div></div>
                  <div class="detail-item"><div class="detail-label">{{ t('sub.ipv6') }}</div><div class="detail-value mono-data">{{ textOrDash(s.ipv6) }}</div></div>
                  <div class="detail-item detail-item--full"><div class="detail-label">{{ t('sub.notes') }}</div><div class="detail-value">{{ textOrDash(s.notes) }}</div></div>
                </div>
              </div>
            </div>
          </Transition>

          <div class="sc-acts" @click.stop>
            <button class="btn sm ghost" @click.stop="openEdit(s)">{{ t('sub.edit') }}</button>
            <button v-if="s.billing_type === 'recurring'" class="btn sm" @click.stop="askRenew(s)">♻️ {{ t('sub.renew') }}</button>
            <button class="btn sm danger" @click.stop="askDelete(s)">{{ t('sub.delete') }}</button>
          </div>
          <div v-if="!filter" class="card-sort">
            <button class="btn sm ghost" @click.stop="moveSub(g.key, s.id, -1)" :aria-label="t('sub.moveUp')">↑</button>
            <button class="btn sm ghost" @click.stop="moveSub(g.key, s.id, 1)" :aria-label="t('sub.moveDown')">↓</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 续费确认弹窗 -->
    <div v-if="renewTarget" class="modal-mask">
      <div class="modal" style="width:460px">
        <button class="modal-x" :aria-label="t('common.close')" @click="renewTarget = null">×</button>
        <h3>♻️ {{ t('sub.renewTitle') }}</h3>
        <p style="font-size:14px;line-height:1.6">{{ t('sub.renewMsg', { name: renewTarget.name }) }}</p>
        <label class="opt" :class="{ on: renewMode === 'today' }">
          <input type="radio" value="today" v-model="renewMode" />
          <div>
            <div>{{ t('sub.renewToday') }}</div>
            <div class="muted opt-d">→ {{ previewToday }}</div>
          </div>
        </label>
        <label class="opt" :class="{ on: renewMode === 'due' }">
          <input type="radio" value="due" v-model="renewMode" />
          <div>
            <div>{{ t('sub.renewDue') }}</div>
            <div class="muted opt-d">→ {{ previewDue }}</div>
          </div>
        </label>
        <div class="modal-foot">
          <button class="btn ghost" @click="renewTarget = null">{{ t('sub.cancel') }}</button>
          <button class="btn" :disabled="renewing" @click="confirmRenew">{{ t('sub.confirm') }}</button>
        </div>
      </div>
    </div>

    <!-- 删除确认（需验证密码） -->
    <div v-if="delTarget" class="modal-mask">
      <div class="modal" style="width:420px">
        <button class="modal-x" :aria-label="t('common.close')" @click="delTarget = null">×</button>
        <h3>🗑️ {{ t('sub.deleteTitle') }}</h3>
        <p style="font-size:14px;line-height:1.6">{{ t('sub.deletePwdTip', { name: delTarget.name }) }}</p>
        <input v-model="delPwd" type="password" :placeholder="t('sub.pwdPh')" @keyup.enter="confirmDelete" />
        <p v-if="delErr" class="err">{{ delErr }}</p>
        <div class="modal-foot">
          <button class="btn ghost" @click="delTarget = null">{{ t('sub.cancel') }}</button>
          <button class="btn danger" :disabled="deleting || !delPwd" @click="confirmDelete">{{ t('sub.delete') }}</button>
        </div>
      </div>
    </div>

    <!-- 添加/编辑订阅 -->
    <div v-if="showForm" class="modal-mask">
      <div class="modal">
        <button class="modal-x" :aria-label="t('common.close')" @click="showForm = false">×</button>
        <h3>{{ form.id ? t('sub.edit') : t('sub.add') }}</h3>

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

          <button class="btn ghost sm" style="margin-top:8px" @click="openBrowser">📚 {{ t('sub.browse') }}</button>

          <details class="icon-lib" @toggle="onIconLibraryToggle">
            <summary>{{ t('sub.icon') }} — {{ t('sub.iconLibrary') }} / URL / {{ t('sub.uploadIcon') }}</summary>
            <input v-model="form.icon" placeholder="🔖 emoji / /static/... / https://..." style="margin:8px 0" />
            <div class="row" style="margin-bottom:8px">
              <input v-model="iconUrl" :placeholder="t('sub.iconUrl')" style="flex:1" />
              <button class="btn ghost sm" @click="importIconUrl">{{ t('sub.iconUrlImport') }}</button>
              <label class="btn ghost sm" style="width:auto">{{ t('sub.uploadIcon') }}
                <input type="file" accept="image/*" hidden @change="uploadIcon" />
              </label>
            </div>
            <div v-if="showIconLibrary" class="lib-grid">
              <button type="button" v-for="it in visibleIconLib" :key="it.slug" class="lib-ico-btn" :title="it.name" @click="form.icon = it.icon">
                <ServiceIcon :src="it.icon" :name="it.name" class="lib-ico" loading="lazy" decoding="async" />
              </button>
            </div>
            <div v-if="showIconLibrary && visibleIconLib.length < iconLib.length" class="row" style="justify-content:center;margin-top:8px">
              <button class="btn ghost sm" @click="showMoreIcons">{{ t('sub.moreIcons') }}</button>
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
              {{ m }} <a href="#" @click.prevent="form.family_members.splice(i, 1)">✕</a>
            </span>
          </div>
          <div class="row">
            <input v-model="newMember" :placeholder="t('sub.familyPh')" @keyup.enter="addMember" style="flex:1" />
            <button class="btn ghost sm" @click="addMember">{{ t('sub.familyAdd') }}</button>
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
          <button class="btn ghost" @click="showForm = false">{{ t('sub.cancel') }}</button>
          <button class="btn" @click="save">{{ t('sub.save') }}</button>
        </div>
      </div>
    </div>

    <!-- 按分类浏览服务库 -->
    <div v-if="showBrowser" class="modal-mask browser">
      <div class="modal">
        <div class="head" style="margin-bottom:10px">
          <h3 style="margin:0">📚 {{ t('sub.browseTitle') }}</h3>
          <button class="btn ghost sm" @click="showBrowser = false">{{ t('common.close') }}</button>
        </div>
        <p class="muted" style="font-size:13px;margin-top:0">{{ t('sub.pickHint') }}</p>
        <input v-model="browserQ" :placeholder="t('sub.searchPh')" style="margin-bottom:12px" />
        <div v-for="g in groupedLib" :key="g.key" class="lib-group">
          <button class="lib-group-t browser-group-t" @click="toggleBrowserGroup(g.key)">
            <span>{{ isBrowserGroupExpanded(g.key) ? '▾' : '▸' }}</span>
            <span>{{ g.label }}</span>
            <span class="muted">({{ g.items.length }})</span>
          </button>
          <div v-if="isBrowserGroupExpanded(g.key)" class="svc-grid">
            <button v-for="s in g.items" :key="s.slug" class="svc" @click="pickFromBrowser(s)">
              <ServiceIcon :src="s.icon" :name="s.name" class="svc-ico" loading="lazy" decoding="async" /> <span>{{ s.name }}</span>
            </button>
          </div>
        </div>
        <p v-if="!groupedLib.length" class="muted">{{ t('reports.empty') }}</p>
      </div>
    </div>

    <div class="toast-wrap">
      <div v-for="tst in toasts" :key="tst.id" class="toast" :class="tst.type">{{ tst.msg }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import MoneyText from '../components/MoneyText.vue'
import ServiceIcon from '../components/ServiceIcon.vue'
import StatusChip from '../components/StatusChip.vue'
import { useAuth } from '../stores/auth'
import { addCycleDate, daysLeft, parseLocalDate, toISODate } from '../utils/date'
import { amountOf, hasBaseEquivalent } from '../utils/money'
import { isExpired, isSoon, renewalStatus } from '../utils/renewal'

const { t } = useI18n()
const auth = useAuth()
const subs = ref([])
const currencies = ref([])
const categories = ref([])
const methods = ref([])
const bundles = ref([])
const iconLib = ref([])
const showIconLibrary = ref(false)
const visibleIconCount = ref(0)
const ICON_BATCH_SIZE = 18
const filter = ref('')
const showForm = ref(false)
const formErr = ref('')
const form = ref({})
const newMember = ref('')
const iconUrl = ref('')
const bundleMode = ref('none')
const newBundleName = ref('')
const suggestions = ref([])

const showBrowser = ref(false)
const browserQ = ref('')
const openBrowserGroups = ref(new Set())

const renewTarget = ref(null)
const renewMode = ref('today')
const renewing = ref(false)

const delTarget = ref(null)
const delPwd = ref('')
const delErr = ref('')
const deleting = ref(false)

// 卡片内联详情：同时只展开一张
const expandedSubId = ref(null)
function isExpanded(id) { return expandedSubId.value === id }
function toggleDetails(id) { expandedSubId.value = expandedSubId.value === id ? null : id }
function detailId(id) { return `sub-detail-${id}` }
function closestElement(target) { return target?.closest ? target : target?.parentElement }
function onCardClick(s, e) {
  // 点击卡片空白处展开/收起；点中按钮、链接、详情区等交互控件则交给控件自身（它们已 @click.stop）
  const target = closestElement(e.target)
  if (target?.closest('button, a, input, select, textarea, label, summary, .sc-detail, .quick-chip')) return
  toggleDetails(s.id)
}

// 基准货币
const baseCurrency = computed(() => {
  const raw = auth.user?.base_currency
  if (typeof raw !== 'string') return 'CNY'
  return raw.trim().toUpperCase() || 'CNY'
})

// 详情字段 helper
const DASH = '—'
function textOrDash(v) { return (v === null || v === undefined || v === '') ? DASH : v }
function boolText(v) { return v ? '✓' : '✗' }
function bundleName(s) {
  const b = bundles.value.find((x) => x.id === s.bundle_id)
  return b ? b.name : ''
}
function categoryName(s) { return catMeta(catKeyOf(s)).name }
function familyText(s) { return s.family_members && s.family_members.length ? s.family_members.join('、') : DASH }

watch([showForm, renewTarget, delTarget, showBrowser], () => {
  const open = showForm.value || renewTarget.value || delTarget.value || showBrowser.value
  document.body.classList.toggle('modal-open', !!open)
})
onBeforeUnmount(() => document.body.classList.remove('modal-open'))

const toasts = ref([])
let toastId = 0
function toast(msg, type = 'ok') {
  const id = ++toastId
  toasts.value.push({ id, msg, type })
  setTimeout(() => { toasts.value = toasts.value.filter((x) => x.id !== id) }, 2600)
}

function payName(s) {
  const p = methods.value.find((x) => x.id === s.payment_method_id)
  return p ? `${p.icon || ''} ${p.name}`.trim() : ''
}
function shouldShowBaseAmount(s) { return hasBaseEquivalent(s, baseCurrency.value) }
function baseAmount(s) { return amountOf(s) }
function cycleText(s) {
  const n = s.cycle_count > 1 ? s.cycle_count + ' ' : ''
  return n + t('sub.' + s.cycle)
}
function dueText(s) {
  const d = daysLeft(s)
  if (d === null) return ''
  if (d < 0) return t('sub.expiredTag')
  return d === 0 ? t('dashboard.today') : t('dashboard.daysLeft', { n: d })
}
function statusOf(s) { return renewalStatus(s) }
function statusChip(s) {
  const st = statusOf(s)
  if (st === 'overdue') return t('sub.statusOverdue')
  if (st === 'soon') return t('sub.statusSoon') + ' · ' + Math.abs(daysLeft(s)) + 'D'
  if (st === 'oneTime') return t('sub.statusLifetime')
  return t('sub.statusSafe')
}

/* ---------- 客户端续费日计算复用共享工具（utils/date.js，与后端 billing.add_cycle 对齐） ---------- */

function blank() {
  return {
    id: null, name: '', plan: '', icon: '', amount: 0, currency: 'CNY',
    category_id: null, payment_method_id: null, bundle_id: null, billing_type: 'recurring',
    cycle: 'month', cycle_count: 1, start_date: toISODate(new Date()),
    next_renewal_date: '', end_date: null, url: '', notes: '', remark: '', ipv4: '', ipv6: '',
    remind_days_before: '7,1', auto_renew: true, is_active: true,
    show_in_calendar: true, family_members: []
  }
}

let suppressAuto = false
function recomputeNext() {
  if (form.value.billing_type !== 'recurring') { form.value.next_renewal_date = ''; return }
  if (form.value.start_date) {
    form.value.next_renewal_date = toISODate(addCycleDate(form.value.start_date, form.value.cycle, form.value.cycle_count))
  }
}
watch(
  () => [form.value.start_date, form.value.cycle, form.value.cycle_count, form.value.billing_type],
  () => { if (!suppressAuto && showForm.value) recomputeNext() }
)

/* ---------- 分组与拖拽排序 ---------- */
// orderMap: { catKey: [subId, ...] } ; catOrder: [catKey, ...]
const orderMap = reactive({})
const catOrder = ref([])
const NONE = 'none'

function catKeyOf(s) { return s.category_id == null ? NONE : String(s.category_id) }
function catMeta(key) {
  if (key === NONE) return { icon: '🗂️', name: t('sub.uncategorized') }
  const c = categories.value.find((x) => String(x.id) === key)
  return c ? { icon: c.icon || '📁', name: c.name } : { icon: '📁', name: key }
}

function rebuild() {
  Object.keys(orderMap).forEach((k) => delete orderMap[k])
  const byCat = {}
  for (const s of subs.value) {
    const k = catKeyOf(s)
    ;(byCat[k] ||= []).push(s)
  }
  for (const k of Object.keys(byCat)) {
    byCat[k].sort((a, b) => (a.sort - b.sort) || (a.id - b.id))
    orderMap[k] = byCat[k].map((s) => s.id)
  }
  // 分类顺序：用户保存的顺序 → 其余出现的分类 → 未分类置底
  const present = new Set(Object.keys(orderMap))
  const saved = (auth.user?.category_order || []).map(String)
  const order = []
  for (const k of saved) if (present.has(k)) { order.push(k); present.delete(k) }
  const rest = [...present].filter((k) => k !== NONE)
    .sort((a, b) => {
      const ca = categories.value.find((x) => String(x.id) === a)
      const cb = categories.value.find((x) => String(x.id) === b)
      return ((ca?.sort ?? 999) - (cb?.sort ?? 999)) || (Number(a) - Number(b))
    })
  order.push(...rest)
  if (present.has(NONE)) order.push(NONE)
  catOrder.value = order
}

const grouped = computed(() =>
  catOrder.value
    .filter((k) => orderMap[k] && orderMap[k].length)
    .map((k) => {
      const meta = catMeta(k)
      const items = orderMap[k].map((id) => subs.value.find((s) => s.id === id)).filter(Boolean)
      return { key: k, icon: meta.icon, name: meta.name, items }
    })
)

// 拖拽状态
let dragCatKey = null
let dragCard = null
const dragOverCat = ref(null)
const dragOverSub = ref(null)
function clearDrag() { dragCatKey = null; dragCard = null; dragOverCat.value = null; dragOverSub.value = null }

async function moveCat(key, dir) {
  if (filter.value) return
  const arr = [...catOrder.value]
  const from = arr.indexOf(key)
  const to = from + dir
  if (from < 0 || to < 0 || to >= arr.length) return
  arr.splice(to, 0, arr.splice(from, 1)[0])
  catOrder.value = arr
  const ids = arr.filter((k) => k !== NONE).map(Number)
  try { await auth.updateMe({ category_order: ids }) } catch { /* ignore */ }
}

async function moveSub(catKey, id, dir) {
  if (filter.value) return
  const arr = [...(orderMap[catKey] || [])]
  const from = arr.indexOf(id)
  const to = from + dir
  if (from < 0 || to < 0 || to >= arr.length) return
  arr.splice(to, 0, arr.splice(from, 1)[0])
  orderMap[catKey] = arr
  try { await api.post('/api/subscriptions/reorder', { ordered_ids: arr }) } catch { /* ignore */ }
}

function onCatDragStart(key, e) {
  if (filter.value) {
    e.preventDefault()
    return
  }
  // 分类排序只允许从分类标题发起，避免卡片空白处拖动误触发分类排序。
  const target = closestElement(e.target)
  if (target?.closest('button, a, input, select, textarea, label') || dragCard) {
    e.preventDefault()
    return
  }
  dragCatKey = key
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
function onCatDragOver(key) { if (!filter.value && dragCatKey && !dragCard) dragOverCat.value = key }
async function onCatDrop(key) {
  if (filter.value || !dragCatKey || dragCard || dragCatKey === key) return clearDrag()
  const arr = [...catOrder.value]
  const from = arr.indexOf(dragCatKey)
  const to = arr.indexOf(key)
  if (from < 0 || to < 0) return clearDrag()
  arr.splice(to, 0, arr.splice(from, 1)[0])
  catOrder.value = arr
  clearDrag()
  // 持久化（只保存真实分类 id，未分类不存）
  const ids = arr.filter((k) => k !== NONE).map(Number)
  try { await auth.updateMe({ category_order: ids }) } catch { /* ignore */ }
}

function onCardDragStart(catKey, id, e) {
  if (filter.value) {
    e.preventDefault()
    return
  }
  dragCard = { catKey, id }
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
function onCardDragOver(catKey, id) {
  if (!filter.value && dragCard && dragCard.catKey === catKey) dragOverSub.value = id
}
async function onCardDrop(catKey, id) {
  if (filter.value || !dragCard || dragCard.catKey !== catKey || dragCard.id === id) return clearDrag()
  const arr = [...orderMap[catKey]]
  const from = arr.indexOf(dragCard.id)
  const to = arr.indexOf(id)
  if (from < 0 || to < 0) return clearDrag()
  arr.splice(to, 0, arr.splice(from, 1)[0])
  orderMap[catKey] = arr
  clearDrag()
  try { await api.post('/api/subscriptions/reorder', { ordered_ids: arr }) } catch { /* ignore */ }
}

async function load() {
  const params = filter.value ? { billing_type: filter.value } : {}
  const { data } = await api.get('/api/subscriptions', { params })
  subs.value = data
  if (expandedSubId.value && !subs.value.some((s) => s.id === expandedSubId.value)) expandedSubId.value = null
  rebuild()
}
function setFilter(f) { filter.value = f; load() }

const visibleIconLib = computed(() => iconLib.value.slice(0, visibleIconCount.value))
function onIconLibraryToggle(e) {
  showIconLibrary.value = e.target.open
  visibleIconCount.value = e.target.open ? ICON_BATCH_SIZE : 0
}
function showMoreIcons() {
  visibleIconCount.value = Math.min(iconLib.value.length, visibleIconCount.value + ICON_BATCH_SIZE)
}

function openNew() {
  form.value = blank(); formErr.value = ''; bundleMode.value = 'none'
  showIconLibrary.value = false
  visibleIconCount.value = 0
  newBundleName.value = ''; suggestions.value = []; showForm.value = true
  recomputeNext()
}
function openEdit(s) {
  suppressAuto = true
  form.value = { ...s, next_renewal_date: s.next_renewal_date || '', family_members: [...(s.family_members || [])] }
  formErr.value = ''; suggestions.value = []
  bundleMode.value = s.bundle_id ? 'join' : 'none'
  newBundleName.value = ''
  showIconLibrary.value = false
  visibleIconCount.value = 0
  showForm.value = true
  nextTick(() => { suppressAuto = false })
}

function onNameInput() {
  const q = (form.value.name || '').toLowerCase().trim()
  suggestions.value = q.length < 1 ? []
    : iconLib.value.filter((s) => s.name.toLowerCase().includes(q)).slice(0, 6)
}
// 服务库分类 key -> 在用户分类名中查找的关键字
const CAT_KEYWORDS = {
  streaming: 'streaming', music: 'music', ai: 'ai', gaming: 'gaming', vps: 'vps',
  carrier: 'carrier', cloud: 'cloud', software: 'software', domain: 'domain',
  education: 'education', news: 'news', fitness: 'fitness', membership: 'membership', other: 'other'
}
function findCategoryByKey(key) {
  const kw = CAT_KEYWORDS[key]
  if (!kw) return null
  const hit = categories.value.find((c) => (c.name || '').toLowerCase().includes(kw))
  return hit ? hit.id : null
}
function serviceCategoryKeys(svc) {
  const keys = Array.isArray(svc?.category_keys) ? svc.category_keys : []
  const clean = keys.map((x) => String(x || '').trim()).filter(Boolean)
  return clean.length ? clean : [svc?.category || 'other']
}
function serviceCategoryLabel(svc, key, index) {
  const labels = Array.isArray(svc?.category_labels) ? svc.category_labels : []
  return labels[index] || (svc?.category === key ? svc.category_label : '') || key
}
const isVpsCategory = computed(() => {
  const c = categories.value.find((x) => x.id === form.value.category_id)
  if (!c) return false
  return (c.name || '').toLowerCase().includes('vps') || (c.name || '').includes('服务器')
})

function pickService(s) {
  form.value.name = s.name
  form.value.icon = s.icon
  if (!form.value.url && s.website) form.value.url = s.website
  // 自动带出分类（按服务库分类映射到用户分类）
  for (const key of serviceCategoryKeys(s)) {
    const cid = findCategoryByKey(key)
    if (cid) { form.value.category_id = cid; break }
  }
  suggestions.value = []
}

function openBrowser() {
  browserQ.value = ''
  openBrowserGroups.value = new Set()
  showBrowser.value = true
}
const browserHasQuery = computed(() => browserQ.value.trim().length > 0)
function isBrowserGroupExpanded(key) { return browserHasQuery.value || openBrowserGroups.value.has(key) }
function toggleBrowserGroup(key) {
  const next = new Set(openBrowserGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openBrowserGroups.value = next
}
const groupedLib = computed(() => {
  const q = browserQ.value.toLowerCase().trim()
  const groups = new Map()
  for (const s of iconLib.value) {
    if (q && !s.name.toLowerCase().includes(q)) continue
    serviceCategoryKeys(s).forEach((key, index) => {
      if (!groups.has(key)) groups.set(key, { key, label: serviceCategoryLabel(s, key, index), items: [] })
      groups.get(key).items.push(s)
    })
  }
  return [...groups.values()]
})
function pickFromBrowser(s) { pickService(s); showBrowser.value = false }

function addMember() {
  const v = newMember.value.trim()
  if (v) { form.value.family_members.push(v); newMember.value = '' }
}

async function importIconUrl() {
  if (!iconUrl.value.trim()) return
  try {
    const { data } = await api.post('/api/icons/from-url', { url: iconUrl.value.trim() })
    form.value.icon = data.url; iconUrl.value = ''
  } catch (e) { formErr.value = e.response?.data?.detail || 'Error' }
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
      bundles.value.push(data)
    } else if (bundleMode.value === 'none') {
      form.value.bundle_id = null
    }
    const payload = { ...form.value }
    if (!payload.next_renewal_date) delete payload.next_renewal_date
    if (payload.id) await api.put(`/api/subscriptions/${payload.id}`, payload)
    else await api.post('/api/subscriptions', payload)
    showForm.value = false
    toast(t('settings.saved'))
    load()
  } catch (e) {
    formErr.value = e.response?.data?.detail || 'Error'
  }
}

/* ---------- 续费 ---------- */
function askRenew(s) { renewTarget.value = s; renewMode.value = 'today' }
const previewToday = computed(() =>
  renewTarget.value ? toISODate(addCycleDate(new Date(), renewTarget.value.cycle, renewTarget.value.cycle_count)) : ''
)
const previewDue = computed(() => {
  if (!renewTarget.value) return ''
  const base = renewTarget.value.next_renewal_date ? parseLocalDate(renewTarget.value.next_renewal_date) : new Date()
  return toISODate(addCycleDate(base, renewTarget.value.cycle, renewTarget.value.cycle_count))
})
async function confirmRenew() {
  if (!renewTarget.value || renewing.value) return
  renewing.value = true
  try {
    const { data } = await api.post(`/api/subscriptions/${renewTarget.value.id}/renew`, { mode: renewMode.value })
    toast(t('sub.renewOk', { date: data.next_renewal_date }))
    renewTarget.value = null
    load()
  } catch (e) {
    toast(e.response?.data?.detail || 'Error', 'err')
  } finally {
    renewing.value = false
  }
}

function askDelete(s) { delTarget.value = s; delPwd.value = ''; delErr.value = '' }
async function confirmDelete() {
  if (!delTarget.value || deleting.value || !delPwd.value) return
  deleting.value = true
  delErr.value = ''
  try {
    await api.delete(`/api/subscriptions/${delTarget.value.id}`, { data: { password: delPwd.value } })
    delTarget.value = null
    toast(t('sub.delete'))
    load()
  } catch (e) {
    delErr.value = e.response?.data?.detail || 'Error'
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  const [c, cat, m, b, lib] = await Promise.all([
    api.get('/api/currencies'),
    api.get('/api/categories'),
    api.get('/api/payment-methods'),
    api.get('/api/bundles'),
    api.get('/api/icons/library')
  ])
  currencies.value = c.data
  categories.value = cat.data
  methods.value = m.data
  bundles.value = b.data
  iconLib.value = lib.data
  load()
})
</script>

<style scoped>
h1 { margin-top: 0; }
.bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.drag-hint { font-size: 12px; }
.err { color: var(--danger); font-size: 13px; }
.ico { width: 18px; height: 18px; vertical-align: middle; border-radius: 4px; }
.auto-tip { color: var(--primary); font-size: 11px; }

/* 分类分组 */
.cat-group { margin-bottom: 22px; border-radius: 14px; transition: outline .12s; outline: 2px dashed transparent; }
.cat-group.drop-cat { outline-color: var(--primary); outline-offset: 4px; }
.cat-head { display: flex; align-items: center; gap: 8px; padding: 6px 4px 12px; cursor: grab; }
.cat-head .grip { color: var(--text-soft); cursor: grab; }
.cat-ico { font-size: 18px; }
.cat-name { font-weight: 700; font-size: 16px; }
.cat-count { background: var(--surface-2); color: var(--text-soft); border-radius: 20px;
  padding: 1px 9px; font-size: 12px; }
.mobile-sort, .card-sort { display: none; gap: 6px; }

/* 信号卡 */
.sub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.sub-card { padding: 18px; cursor: pointer; position: relative; overflow: hidden;
  transition: transform .22s cubic-bezier(.2,.8,.2,1), box-shadow .22s ease, border-color .18s ease, background .18s ease; }
.sub-card:focus-visible { outline: 2px solid var(--primary); outline-offset: 3px; }
.sub-card.expanded { border-color: color-mix(in srgb, var(--primary) 45%, var(--border)); box-shadow: var(--shadow-lg);
  background: linear-gradient(180deg, color-mix(in srgb, var(--signal-cyan) 4%, var(--surface)), var(--surface)); }
/* 续费状态信号轨：safe / soon / overdue */
.status-strip { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.status-strip.ok { background: var(--success); opacity: .35; }
.status-strip.soon { background: var(--warning); opacity: .85; }
.status-strip.overdue { background: var(--danger); }
.status-strip.oneTime { background: var(--text-soft); opacity: .22; }
.sub-card::after { content: ''; position: absolute; top: 0; left: -60%; width: 40%; height: 100%;
  background: linear-gradient(100deg, transparent, color-mix(in srgb, var(--primary) 12%, transparent), transparent);
  transform: skewX(-18deg); opacity: 0; transition: opacity .3s; pointer-events: none; }
.sub-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg);
  border-color: color-mix(in srgb, var(--primary) 40%, var(--border)); }
.sub-card:hover::after { opacity: 1; animation: sheen .8s ease; }
@keyframes sheen { from { left: -60%; } to { left: 130%; } }
.sub-card:hover .sc-ico { transform: scale(1.05) rotate(-2deg); }
.sub-card.inactive { opacity: .55; }
.sub-card.expired { border-color: var(--danger); box-shadow: 0 0 0 1px var(--danger), var(--shadow); }
.sub-card.soon { border-color: var(--warning); box-shadow: 0 0 0 1px var(--warning), var(--shadow); }
.sub-card.drop-card { border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-soft); }
.sc-head { display: flex; align-items: center; gap: 12px; }
.sc-ico { width: 44px; height: 44px; border-radius: 12px; object-fit: contain; border: 1px solid var(--border);
  flex-shrink: 0; background: var(--surface-2); transition: transform .25s cubic-bezier(.2,.8,.2,1); }
.sc-ico.emoji { display: flex; align-items: center; justify-content: center; font-size: 26px; }
.sc-title { flex: 1; min-width: 0; }
.sc-name { font-weight: 700; font-size: 17px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sc-plan { font-size: 12px; overflow-wrap: anywhere; }
.card-grip { flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; border: none; background: transparent; color: var(--text-soft); cursor: grab;
  padding: 5px 6px; border-radius: 8px; line-height: 1; user-select: none; }
.card-grip:hover { background: var(--surface-2); color: var(--text); }
.card-grip:active { cursor: grabbing; }
.card-detail-toggle { flex-shrink: 0; border: none; background: transparent; color: var(--text-soft); cursor: pointer;
  padding: 5px 8px; border-radius: 8px; line-height: 1; font-size: 14px; }
.card-detail-toggle:hover { background: var(--surface-2); color: var(--text); }
.sc-signal { display: grid; gap: 6px; margin-top: 14px; }
.sc-amount { font-size: 28px; font-weight: 800; letter-spacing: -.02em; }
.sc-amount .cur { font-size: 15px; font-weight: 500; }
.sc-amount .cycle { font-size: 14px; font-weight: 500; }
.sc-base-amount { display: flex; align-items: baseline; gap: 6px; font-size: 12px; color: var(--text-soft); }
.sc-due { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.sc-due .due { font-weight: 700; }
.sc-due-text { font-size: 12px; color: var(--text-soft); }
.sc-due.ok .due { color: var(--text); }
.sc-due.soon .due, .sc-due.soon .sc-due-text { color: var(--warning); }
.sc-due.overdue .due, .sc-due.overdue .sc-due-text { color: var(--danger); }
.sc-due.oneTime .sc-due-text { color: var(--text-soft); font-style: italic; }
.expired-banner { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); font-size: 12px; font-weight: 800;
  border-radius: 8px; padding: 4px 10px; display: inline-block; width: fit-content; }
.soon-banner { background: color-mix(in srgb, var(--warning) 16%, transparent); color: var(--warning); font-size: 12px; font-weight: 800;
  border-radius: 8px; padding: 4px 10px; display: inline-block; width: fit-content; }
.sc-quick { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.quick-chip { display: inline-flex; align-items: center; max-width: 100%; border: 1px solid var(--border); border-radius: 999px;
  padding: 3px 8px; color: var(--text-soft); background: color-mix(in srgb, var(--surface-2) 76%, transparent); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sc-detail { margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--border); display: grid; gap: 12px; }
.detail-section { border: 1px solid var(--border); border-radius: 14px; padding: 12px;
  background: color-mix(in srgb, var(--surface-2) 76%, transparent); }
.detail-title { font-size: 13px; font-weight: 850; color: var(--primary); margin-bottom: 9px; letter-spacing: -.01em; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px 12px; }
.detail-item { min-width: 0; }
.detail-item--full { grid-column: 1 / -1; }
.detail-label { font-size: 11px; color: var(--text-soft); margin-bottom: 2px; }
.detail-value { font-size: 13px; line-height: 1.45; word-break: break-word; }
.detail-value a { color: var(--primary); text-decoration: none; }
.detail-value a:hover { text-decoration: underline; }
.detail-enter-active, .detail-leave-active { transition: opacity .16s ease, transform .16s ease; }
.detail-enter-from, .detail-leave-to { opacity: 0; transform: translateY(-4px); }
.due.soon { color: var(--warning); font-weight: 600; }
.due.overdue { color: var(--danger); font-weight: 700; }
.tag.one_time { background: #fef3c7; color: #b45309; }
.sc-acts { display: flex; gap: 6px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); }
.sc-acts .btn { flex: 1; }

/* 续费弹窗单选 */
.opt { display: flex; align-items: flex-start; gap: 10px; border: 1px solid var(--border); border-radius: 10px;
  padding: 12px; margin-top: 10px; cursor: pointer; font-size: 14px; color: var(--text); width: auto; }
.opt.on { border-color: var(--primary); background: var(--primary-soft); }
.opt input { width: auto; margin-top: 3px; }
.opt-d { font-size: 12px; margin-top: 3px; }

/* 表单内复用样式 */
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

.browser .modal { width: 560px; }
.lib-group { margin-bottom: 14px; }
.lib-group-t { font-size: 13px; font-weight: 600; color: var(--text-soft); margin-bottom: 8px; }
.browser-group-t { width: 100%; display: flex; align-items: center; gap: 6px; padding: 0; border: none; background: transparent; cursor: pointer; text-align: left; }
.svc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.svc { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--surface); cursor: pointer; font-size: 13px; color: var(--text);
  text-align: left; transition: border-color .12s, background .12s; }
.svc:hover { border-color: var(--primary); background: var(--primary-soft); }
.svc-ico { width: 22px; height: 22px; border-radius: 5px; object-fit: contain; flex-shrink: 0; }
.svc span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

@media (max-width: 720px) {
  .bar { align-items: stretch; }
  .bar .btn { width: 100%; }
  .sub-grid { grid-template-columns: 1fr; }
  .sc-head { align-items: flex-start; gap: 10px; }
  .sc-name { font-size: 16px; white-space: normal; line-height: 1.3; }
  .sc-amount { font-size: 24px; overflow-wrap: anywhere; }
  .sc-due { align-items: flex-start; flex-wrap: wrap; }
  .quick-chip { white-space: normal; line-height: 1.35; border-radius: 12px; }
  .drag-hint { display: none; }
  .cat-head { cursor: default; flex-wrap: wrap; }
  .cat-head .grip { display: none; }
  .mobile-sort { display: inline-flex; margin-left: auto; }
  .sub-card { cursor: pointer; padding: 16px; }
  .card-grip { display: none; }
  .detail-section { padding: 10px; }
  .detail-grid { grid-template-columns: 1fr; }
  .detail-value { overflow-wrap: anywhere; }
  .sc-acts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sc-acts .btn { min-height: 44px; }
  .card-sort { display: grid; grid-template-columns: repeat(2, 1fr); margin-top: 8px; }
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
  .browser-group-t { min-height: 44px; padding: 6px 0; }
  .svc { min-height: 44px; }
  .svc span { white-space: normal; line-height: 1.3; }
}
</style>

