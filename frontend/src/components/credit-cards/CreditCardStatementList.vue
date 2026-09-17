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
          <span v-else-if="s.repaid_amount > 0" class="stmt-partial-tag">
            {{ t('creditCards.statementPartialTag', { paid: formatMoney(s.repaid_amount), remaining: formatMoney(remainingOf(s)) }) }}
          </span>
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
                @click="onRepayAction(s)"
              >
                {{ s.is_repaid ? t('creditCards.unmarkRepaid') : t('creditCards.markRepaid') }}
              </button>
              <!-- 清零重算入口（十一审 M1）：部分还款错录金额的唯一修正——
                   清除该账单全部已登记还款（恢复全额待还），与继续还款分开 -->
              <button
                v-if="!s.is_repaid && s.repaid_amount > 0"
                type="button"
                class="btn ghost sm"
                :disabled="markPending"
                @click="requestPurgeRepayment(s)"
              >
                {{ t('creditCards.purgeRepayment') }}
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

  <!-- 单期部分还款输入框（AppModal 就地渲染） -->
  <RepaymentModal
    v-if="repayOpen && repayTarget"
    :target="repayTarget"
    :pending="markPending"
    :server-error="repayServerError"
    @close="repayOpen = false"
    @confirm="onStatementRepay"
  />

  <!-- 取消还款标记确认（有还款记录时清零是破坏性操作） -->
  <AppModal
    v-model="confirmModalOpen"
    :title="confirm.state.value?.title || ''"
    width="430px"
    :close-label="t('common.close')"
    :pending="confirm.state.value?.pending"
    @close="confirm.close"
  >
    <p class="stmt-confirm-copy">{{ confirm.state.value?.message }}</p>
    <template #footer>
      <button type="button" class="btn ghost" :disabled="confirm.state.value?.pending" @click="confirm.close">{{ t('creditCards.cancel') }}</button>
      <button type="button" class="btn danger" :disabled="confirm.state.value?.pending" @click="confirm.confirm">
        {{ confirm.state.value?.pending ? t('common.processing') : (confirm.state.value?.confirmLabel || t('creditCards.unmarkRepaid')) }}
      </button>
    </template>
  </AppModal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api'
import MoneyText from '../MoneyText.vue'
import AppModal from '../AppModal.vue'
import RepaymentModal from './RepaymentModal.vue'
import { useBreakpoint } from '../../composables/useBreakpoint'
import { useConfirm } from '../../composables/useConfirm'
import { statementCycleLabel } from '../../utils/creditCardDates'
import { statementRemainingAmount } from '../../utils/creditCardRepayment'
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

// 单期账单标记/取消已还款（明细区操作）；成功后本地更新并通知父级。
// 三路分派（部分还款功能）：已还 → 取消标记（有还款记录先确认——清零重算
// 是错录金额的唯一修正入口）；未还且有金额 → 弹金额输入框登记还款；
// 金额未知 → 保留原 PATCH 快捷全量标记（没有「部分」可言）。
const confirm = useConfirm()
// AppModal 的 v-model 需要 boolean；useConfirm.state 为 null/对象，桥接一层
const confirmModalOpen = computed({
  get: () => Boolean(confirm.state.value?.open),
  set: (v) => { if (!v) confirm.close() }
})
const repayOpen = ref(false)
const repayTarget = ref(null)
// 明细入口无 toast：服务端失败原因显示在弹窗内（审核 Medium 5——
// 错误留在弹窗后方用户看不到，会误以为按钮没生效）
const repayServerError = ref('')

function remainingOf(s) {
  return statementRemainingAmount(s.total_due, s.repaid_amount) ?? 0
}

function onRepayAction(s) {
  if (s.is_repaid) {
    if (s.repaid_amount > 0) {
      confirm.open({
        title: t('creditCards.unmarkRepaidConfirmTitle'),
        message: t('creditCards.unmarkRepaidConfirmMessage', { amount: formatMoney(s.repaid_amount) }),
        danger: true,
        onConfirm: () => toggleRepaid(s)
      })
    } else {
      toggleRepaid(s)
    }
    return
  }
  // 部分还款账单（十一审 M1）：按钮只打开弹窗继续登记；清零走独立入口
  // mismatch 账单走原 PATCH 单期标记（后端 repay 明确拒绝勾稽失败账单，
  // 弹窗会必然失败）；金额未知走 PATCH 快捷标记
  if (s.verify_status === 'ok' && s.total_due != null && remainingOf(s) > 0) {
    repayTarget.value = {
      kind: 'statement',
      name: cycleName(s),
      statementId: s.id,
      remaining: remainingOf(s),
      repaidAmount: s.repaid_amount || 0,
      cyclesText: cycleName(s)
    }
    repayServerError.value = ''
    repayOpen.value = true
    return
  }
  toggleRepaid(s) // 金额未知等：保留原快捷标记
}

// 清除部分还款记录（十一审 M1 清零重算）：PATCH is_repaid=false——后端把
// repaid_amount 清零（错录金额的唯一修正入口），破坏性操作需确认
function requestPurgeRepayment(s) {
  confirm.open({
    title: t('creditCards.unmarkRepaidConfirmTitle'),
    message: t('creditCards.unmarkRepaidConfirmMessage', { amount: formatMoney(s.repaid_amount) }),
    danger: true,
    onConfirm: () => toggleRepaid(s, false)  // 清零重算：复位为未还
  })
}

// 还款弹窗确认：PATCH 语义已由 POST /repay 承担；原位更新行 + 通知父级
async function onStatementRepay(amount) {
  const target = repayTarget.value
  if (!target || markPending.value) return
  markPending.value = true
  markErrorId.value = null
  repayServerError.value = ''
  try {
    const { data } = await api.post(
      `/api/credit-cards/statements/${target.statementId}/repay`,
      { amount }
    )
    if (data?.statement) {
      const idx = statements.value.findIndex((x) => x.id === target.statementId)
      if (idx >= 0) Object.assign(statements.value[idx], data.statement)
    }
    // 自动补标（十审 M2）：还清最新账单时后端会同步结清更早的未还账单——
    // 重载明细列表，否则旧行仍显示未还（点它会被「已还清」拒绝，界面矛盾）
    if (data?.auto_marked > 0) {
      await load()
    }
    emit('repaid-changed', data?.card || null)
    repayOpen.value = false
  } catch (e) {
    // 失败要响亮：原因直接显示在弹窗内（弹窗不关，用户输入保留）
    repayServerError.value = e.response?.data?.detail || t('creditCards.repayFailed')
  } finally {
    markPending.value = false
  }
}

async function toggleRepaid(s, targetState) {
  if (markPending.value) return
  markPending.value = true
  markErrorId.value = null
  const next = targetState !== undefined ? targetState : !s.is_repaid
  try {
    const { data } = await api.patch(
      `/api/credit-cards/statements/${s.id}/repaid`,
      { is_repaid: next }
    )
    // 用服务端重新派生的账单原位更新（is_overdue/overdue_days 随标记变化，
    // 避免「已还」与「已逾期」同时显示或逾期徽标漏掉）
    if (data?.statement) Object.assign(s, data.statement)
    else s.is_repaid = next
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
.stmt-partial-tag { flex: 0 0 auto; padding: 2px 7px; border-radius: 999px; background: color-mix(in srgb, var(--primary) 10%, transparent); color: var(--primary-text, var(--primary)); font-size: 11px; font-weight: 750; }
.stmt-confirm-copy { margin: 0; font-size: 13px; line-height: 1.6; }
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
