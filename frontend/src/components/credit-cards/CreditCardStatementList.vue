<template>
  <section class="stmt-section">
    <div class="stmt-head">
      <strong>{{ t('creditCards.statementsTitle') }}</strong>
      <!-- 刷新失败优先于空列表文案：补拉后刷新失败时「还没有账单」会掩盖错误 -->
      <span v-if="error" class="stmt-err">{{ t('creditCards.statementsLoadFailed') }}
        <button type="button" class="btn ghost sm" @click="load">{{ t('imap.retry') }}</button>
      </span>
      <span v-else-if="loaded && !statements.length" class="muted stmt-empty">
        {{ unmatchedCount ? t('creditCards.statementsUnmatched') : t('creditCards.statementsEmpty') }}
      </span>
    </div>

    <ul v-if="statements.length" class="stmt-list">
      <li v-for="s in statements" :key="s.id" class="stmt-item">
        <button type="button" class="stmt-summary" @click="toggle(s.id)" :aria-expanded="expanded === s.id">
          <span class="stmt-period">{{ cycleName(s) }}</span>
          <span v-if="overdueDays(s) != null" class="stmt-overdue-tag">{{ t('creditCards.overdueDays', { n: overdueDays(s) }) }}</span>
          <span v-if="s.is_repaid" class="stmt-repaid-tag">{{ t('creditCards.repaidTag') }}</span>
          <MoneyText class="stmt-amount" :class="{ repaid: s.is_repaid, overdue: s.is_overdue }" :value="s.total_due" currency="CNY" position="prefix" />
          <span class="stmt-due muted">{{ s.due_date ? t('creditCards.dueOn', { d: s.due_date }) : '' }}</span>
          <span class="stmt-verify" :class="s.verify_status === 'ok' ? 'ok' : 'bad'">
            {{ s.verify_status === 'ok' ? '✓' : '⚠' }}
          </span>
        </button>
        <div v-if="expanded === s.id" class="stmt-detail">
          <div v-if="detailLoading" class="muted">{{ t('common.loading') }}</div>
          <div v-else-if="detailError" class="stmt-err">{{ t('creditCards.statementsLoadFailed') }}
            <button type="button" class="btn ghost sm" @click="toggle(s.id)">{{ t('imap.retry') }}</button>
          </div>
          <template v-else-if="detail">
            <div class="stmt-period-detail muted">{{ s.bill_period_start && s.bill_period_end ? `${s.bill_period_start} ~ ${s.bill_period_end}` : '' }}</div>
            <div class="stmt-actions">
              <button
                type="button"
                class="btn ghost sm"
                :disabled="markPending"
                @click="toggleRepaid(s)"
              >
                {{ s.is_repaid ? t('creditCards.unmarkRepaid') : t('creditCards.markRepaid') }}
              </button>
              <span v-if="markErrorId === s.id" class="stmt-err" role="alert">{{ t('creditCards.markRepaidFailed') }}</span>
            </div>
            <div class="stmt-meta">
              <span v-if="s.min_due != null">{{ t('creditCards.minDue') }}: <MoneyText :value="s.min_due" currency="CNY" position="prefix" /></span>
              <span v-if="s.credit_limit != null">{{ t('creditCards.creditLimit') }}: {{ formatMoney(s.credit_limit) }}</span>
            </div>
            <div v-if="isDesktop" class="tbl-wrap">
              <table>
                <thead><tr><th>{{ t('creditCards.txDate') }}</th><th>{{ t('creditCards.txDesc') }}</th><th class="num">{{ t('creditCards.txAmount') }}</th><th>{{ t('creditCards.txType') }}</th></tr></thead>
                <tbody>
                  <tr v-for="item in detail" :key="item.id">
                    <td class="mono-data">{{ item.trans_date || item.trans_date_raw || '—' }}</td>
                    <td class="stmt-desc">{{ item.description }}<em v-if="item.installment_note" class="stmt-inst">{{ item.installment_note }}</em></td>
                    <td class="num"><MoneyText :value="item.amount" currency="CNY" position="prefix" /></td>
                    <td><span class="tag">{{ typeLabel(item.tx_type) }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="ledger">
              <div v-for="item in detail" :key="item.id" class="ld-row">
                <span class="ld-desc">{{ item.description }}<em v-if="item.installment_note" class="stmt-inst">{{ item.installment_note }}</em></span>
                <span class="ld-meta mono-data">{{ item.trans_date || item.trans_date_raw }}</span>
                <MoneyText class="ld-amt" :value="item.amount" currency="CNY" position="prefix" />
              </div>
            </div>
            <p v-if="truncated" class="muted stmt-truncated">{{ t('creditCards.truncatedHint') }}</p>
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import MoneyText from '../MoneyText.vue'
import { useBreakpoint } from '../../composables/useBreakpoint'
import { statementCycleLabel } from '../../utils/creditCardDates'
import { formatMoney } from '../../utils/money'

// 账单明细：打开卡片详情时懒加载；金额一律 MoneyText（与订阅卡同源）。
const props = defineProps({
  cardId: { type: Number, required: true },
  // 父级递增触发账单列表重载（补拉新账单落库后）
  refreshKey: { type: Number, default: 0 }
})

// 还款标记变化时通知父级（携带更新后的卡片派生数据，null=孤立账单）
const emit = defineEmits(['repaid-changed'])

const { t } = useI18n()
const statements = ref([])
const loaded = ref(false)
const error = ref(false)
const unmatchedCount = ref(0)
const expanded = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref(false)
const truncated = ref(false)
const markPending = ref(false)
const markErrorId = ref(null) // 标记失败的账单 id：错误只显示在对应账单下，不串位
let detailSeq = 0
const isDesktop = useBreakpoint('(min-width: 721px)')

// 本卡视图只显示 matched 记录；未匹配卡的提示在设置页同步结果里展示

const TYPE_KEYS = {
  purchase: 'purchase', payment: 'payment', refund: 'refund',
  installment: 'installment', interest: 'interest', fee: 'fee', unknown: 'unknown'
}
const typeLabel = (type) => t(`creditCards.txType_${TYPE_KEYS[type] || 'unknown'}`)

// 账单行主标签：按账单月份命名（「26年8月账单」，用户口径），原始周期在展开区显示
const cycleName = (s) => {
  const month = statementCycleLabel(s)
  return month ? t('creditCards.statementCycleName', { month }) : t('creditCards.periodUnknown')
}
// 逾期天数由后端按业务时区算好返回（overdue_days），前端不重算——浏览器
// 时区与服务端不同时会少算/隐藏徽标
const overdueDays = (s) => (s.is_overdue ? s.overdue_days : null)

let loadSeq = 0

async function load() {
  // 请求序号防竞态：refreshKey 触发的刷新与初始加载并发时，
  // 旧响应最后写回会让刚补拉出的账单「消失」
  const seq = ++loadSeq
  error.value = false
  try {
    const { data } = await api.get(`/api/credit-cards/${props.cardId}/statements`)
    if (seq !== loadSeq) return
    statements.value = data.statements || []
    unmatchedCount.value = data.unmatched_count || 0
    loaded.value = true
  } catch {
    if (seq !== loadSeq) return
    error.value = true
  }
}

async function toggle(id) {
  if (expanded.value === id) {
    expanded.value = null
    detail.value = null
    detailError.value = false
    return
  }
  expanded.value = id
  detail.value = null
  detailError.value = false
  detailLoading.value = true
  const seq = ++detailSeq
  try {
    const { data } = await api.get(`/api/credit-cards/${props.cardId}/statements/${id}/items`)
    if (seq !== detailSeq || expanded.value !== id) return // 已切换到其他账单，丢弃过期响应
    detail.value = data.items || []
    truncated.value = Boolean(data.truncated)
  } catch {
    if (seq === detailSeq && expanded.value === id) {
      // 失败要响亮：不能把网络错误伪装成「无明细」
      detailError.value = true
    }
  } finally {
    if (seq === detailSeq) detailLoading.value = false
  }
}

// 单期账单标记/取消已还款（明细区操作）；成功后本地更新并通知父级
async function toggleRepaid(s) {
  if (markPending.value) return
  markPending.value = true
  markErrorId.value = null
  try {
    const { data } = await api.patch(
      `/api/credit-cards/statements/${s.id}/repaid`,
      { is_repaid: !s.is_repaid }
    )
    // 用服务端重新派生的账单原位更新（is_overdue/overdue_days 随标记变化，
    // 避免「已还」与「已逾期」同时显示或逾期徽标漏掉）
    if (data?.statement) Object.assign(s, data.statement)
    else s.is_repaid = !s.is_repaid
    // 界线推进改变了卡片派生字段（next_due_date 等）：带上最新卡片供父级替换
    emit('repaid-changed', data?.card || null)
  } catch {
    // 失败要响亮：不能让用户以为标记成功；错误只挂在对应账单下
    markErrorId.value = s.id
  } finally {
    markPending.value = false
  }
}

// refreshKey 由父级递增触发重载（如补拉新账单落库后刷新明细）
watch(() => [props.cardId, props.refreshKey], ([id]) => {
  if (id) load()
}, { immediate: true })
</script>

<style scoped>
.stmt-section { margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px; }
.stmt-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.stmt-empty { font-size: 12px; }
.stmt-err { font-size: 12px; color: var(--danger-text); }
.stmt-hint { margin: 0 0 8px; font-size: 12px; color: var(--warning-text); }
.stmt-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.stmt-item { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.stmt-summary { display: flex; align-items: center; gap: 8px; width: 100%; padding: 9px 12px;
  border: 0; background: var(--surface-2); font: inherit; cursor: pointer; text-align: left; }
.stmt-summary:hover { background: color-mix(in srgb, var(--primary) 6%, var(--surface-2)); }
.stmt-period { font-weight: 750; font-size: 12px; }
.stmt-repaid-tag { flex: 0 0 auto; padding: 2px 7px; border-radius: 999px; background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success-text); font-size: 11px; font-weight: 750; }
.stmt-overdue-tag { flex: 0 0 auto; padding: 2px 7px; border-radius: 999px; background: color-mix(in srgb, var(--danger) 13%, transparent); color: var(--danger-text); font-size: 11px; font-weight: 750; white-space: nowrap; }
.stmt-amount.repaid { opacity: .55; text-decoration: line-through; }
.stmt-amount.overdue { color: var(--danger-text); }
.stmt-period-detail { min-height: 1em; font-size: 11px; }
.stmt-actions { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.stmt-amount { margin-left: auto; font-weight: 800; }
.stmt-due { font-size: 11px; white-space: nowrap; }
.stmt-verify { flex: 0 0 auto; width: 18px; height: 18px; display: inline-flex; align-items: center;
  justify-content: center; border-radius: 999px; font-size: 11px; font-weight: 800; }
.stmt-verify.ok { background: color-mix(in srgb, var(--success) 14%, transparent); color: var(--success-text); }
.stmt-verify.bad { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning-text); }
.stmt-detail { padding: 10px 12px; border-top: 1px solid var(--border); }
.stmt-meta { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: var(--text-soft); margin-bottom: 8px; }
.stmt-desc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 260px; }
.stmt-inst { font-style: normal; color: var(--text-soft); font-size: 11px; margin-left: 5px; }
.ledger { display: grid; gap: 6px; }
.ledger .ld-row { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; }
.ledger .ld-desc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.ledger .ld-meta { font-size: 11px; color: var(--text-soft); }
.ledger .ld-amt { grid-column: 2; font-weight: 750; }
.tbl-wrap { overflow-x: auto; }
</style>
