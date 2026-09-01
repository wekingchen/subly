<template>
  <div class="credit-cards-page">
    <section class="cards-hero radar-grid-bg">
      <div class="hero-copy">
        <div class="hero-kicker"><span class="signal-dot"></span>{{ t('creditCards.kicker') }}</div>
        <h1 tabindex="-1">{{ t('creditCards.title') }}</h1>
        <p>{{ t('creditCards.subtitle') }}</p>
      </div>
      <div class="hero-actions">
        <span class="mono-data">{{ t('creditCards.cardCount', { n: cards.length }) }}</span>
        <button type="button" class="btn" :disabled="mutationPending" @click="openAdd">+ {{ t('creditCards.add') }}</button>
      </div>
    </section>

    <CreditCardStats
      v-if="canShowCards"
      :cards="cards"
      :sort-by-interest-free="sortByInterestFree"
      :outstanding="outstanding"
      :outstanding-error="outstandingError"
      @toggle-interest-sort="sortByInterestFree = !sortByInterestFree"
      @retry-outstanding="refreshOutstanding().catch(() => {})"
    />

    <DataState
      v-if="dataState !== 'ready' && dataState !== 'empty'"
      :state="dataState"
      :trust="dataState === 'stale' ? 'stale' : 'unknown'"
      :compact="dataState === 'refreshing' || dataState === 'stale'"
      :loading-title="t('creditCards.loading')"
      :error-title="t('creditCards.loadFailed')"
      :stale-title="t('creditCards.staleTitle')"
      :stale-description="t('creditCards.staleDescription')"
      @retry="load"
    />

    <section v-if="dataState === 'empty'" class="empty-state card">
      <div class="empty-card" aria-hidden="true"><span></span></div>
      <h2>{{ t('creditCards.emptyTitle') }}</h2>
      <p>{{ t('creditCards.emptyDescription') }}</p>
      <button type="button" class="btn" @click="openAdd">+ {{ t('creditCards.add') }}</button>
    </section>

    <section v-if="canShowCards && cards.length" class="cards-grid" :aria-label="t('creditCards.listLabel')">
      <CreditCardItem
        v-for="card in visibleCards"
        :key="card.id"
        :card="card"
        :highlight="sortByInterestFree && bestInterestFree?.id === card.id"
        :disabled="mutationPending"
        :outstanding-entry="outstandingPerCard.get(card.id) || null"
        @view="openDetail"
        @edit="openEdit"
        @delete="requestDelete"
        @mark-repaid="requestMarkRepaid"
      />
    </section>

    <aside class="page-disclaimer" role="note">
      <span aria-hidden="true">!</span>
      <div>
        <strong>{{ t('creditCards.disclaimerTitle') }}</strong>
        <p>{{ t('creditCards.disclaimer') }}</p>
      </div>
    </aside>

    <CreditCardFormModal
      v-if="formOpen"
      :card="formTarget"
      :pending="mutationPending"
      :error="formError"
      @close="closeForm"
      @save="submitForm"
    />

    <CreditCardDetailModal
      v-if="detailTarget"
      :card="detailTarget"
      @close="detailTarget = null"
      @edit="editFromDetail"
      @statements-changed="(updated) => { applyCardUpdate(updated); refreshOutstanding().catch(() => {}) }"
    />

    <AppModal
      v-model="confirmOpen"
      :title="confirm.state.value?.title || ''"
      width="430px"
      :close-label="t('common.close')"
      :pending="confirm.state.value?.pending"
      description-id="credit-card-delete-description"
      @close="confirm.close"
    >
      <p id="credit-card-delete-description" class="delete-copy">{{ confirm.state.value?.message }}</p>
      <p v-if="confirm.state.value?.error" class="delete-error" role="alert">{{ confirm.state.value.error }}</p>
      <template #footer>
        <button type="button" class="btn ghost" :disabled="confirm.state.value?.pending" @click="confirm.close">{{ t('creditCards.cancel') }}</button>
        <button
          type="button"
          class="btn"
          :class="confirm.state.value?.danger ? 'danger' : ''"
          :disabled="confirm.state.value?.pending"
          @click="confirm.confirm"
        >
          {{ confirm.state.value?.pending ? t('common.processing') : (confirm.state.value?.confirmLabel || t('creditCards.confirmDelete')) }}
        </button>
      </template>
    </AppModal>

    <AppToastRegion :toasts="toasts" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppModal from '../components/AppModal.vue'
import AppToastRegion from '../components/AppToastRegion.vue'
import CreditCardDetailModal from '../components/credit-cards/CreditCardDetailModal.vue'
import CreditCardFormModal from '../components/credit-cards/CreditCardFormModal.vue'
import CreditCardItem from '../components/credit-cards/CreditCardItem.vue'
import CreditCardStats from '../components/credit-cards/CreditCardStats.vue'
import DataState from '../components/DataState.vue'
import { buildRepaidScopeText, orderCards } from '../utils/creditCardDates'
import { useConfirm } from '../composables/useConfirm'
import { useCreditCards } from '../composables/useCreditCards'
import { useToasts } from '../composables/useToasts'

const { t } = useI18n()
const confirm = useConfirm()
const { toasts, add: toast } = useToasts()
const { cards, dataState, mutationPending, outstanding, outstandingError, load, refreshOutstanding, markCardRepaid, save, remove } = useCreditCards()

// 单期标记后后端返回更新卡片（界线推进 → next_due_date 等派生变化）：
// 原位替换列表数据并同步已打开的详情弹窗，UI 立即顺延无需重载
function applyCardUpdate(updated) {
  if (!updated?.id) return
  const index = cards.value.findIndex((item) => item.id === updated.id)
  if (index >= 0) cards.value.splice(index, 1, updated)
  if (detailTarget.value?.id === updated.id) detailTarget.value = updated
}
const formOpen = ref(false)
const formTarget = ref(null)
const formError = ref('')
const detailTarget = ref(null)
const canShowCards = computed(() => !['loading', 'error'].includes(dataState.value))

// 免息期排序：点击"最长免息期"统计卡切换。默认按计划还款日由近到远，
// 开启后列表按 interest_free_days 从长到短排序，并高亮当前最长的卡。
const sortByInterestFree = ref(false)
const bestInterestFree = computed(() => {
  const active = cards.value.filter((card) => card.is_active && Number.isFinite(card.interest_free_days))
  return active.length
    ? active.reduce((best, card) => (card.interest_free_days > best.interest_free_days ? card : best))
    : null
})
const visibleCards = computed(() => {
  // 默认：启用卡按计划还款日由近到远（后端派生 days_until_due，业务时区口径；
  // 标记已还款顺延后响应卡片原位替换，自动重排）。免息排序开启时按免息期降序。
  return orderCards(cards.value, { byInterestFree: sortByInterestFree.value })
})

// card_id → { total_due, count }：卡片上「标记已还款」按钮的数据源
const outstandingPerCard = computed(() => {
  const map = new Map()
  for (const entry of outstanding.value?.per_card || []) {
    if (entry.card_id != null) map.set(entry.card_id, entry)
  }
  return map
})

function formatAmount(value) {
  const n = Number(value)
  return Number.isInteger(n) ? n.toLocaleString('zh-CN') : n.toFixed(2)
}

// 标记范围文案与按钮提示共用同一实现（见 creditCardDates.buildRepaidScopeText）
function buildScopeText(entry) {
  return buildRepaidScopeText(entry, t)
}

const confirmOpen = computed({
  get: () => Boolean(confirm.state.value?.open),
  set: (value) => { if (!value) confirm.close() }
})

function openAdd() {
  formTarget.value = null
  formError.value = ''
  formOpen.value = true
}

function openEdit(card) {
  formTarget.value = card
  formError.value = ''
  formOpen.value = true
}

function closeForm() {
  if (mutationPending.value) return
  formOpen.value = false
  formTarget.value = null
  formError.value = ''
}

function openDetail(card) {
  detailTarget.value = card
}

function editFromDetail(card) {
  detailTarget.value = null
  openEdit(card)
}

async function submitForm(payload, localError = '') {
  if (!payload) {
    formError.value = localError
    return
  }
  formError.value = ''
  try {
    const wasEditing = Boolean(formTarget.value?.id)
    const result = await save(formTarget.value, payload)
    closeForm()
    if (wasEditing) {
      toast(t('creditCards.updated'))
    } else {
      // 批量数量以 save() 的归一化结果为准（空尾号按 1 张计），与实际持久化一致。
      toast(t('creditCards.batchCreated', { n: result?.created ?? 1 }))
    }
  } catch (error) {
    const batch = error.batch
    if (batch && batch.created > 0) {
      const reason = error.response?.data?.detail || t('common.networkError')
      // 结构化错误：message 给弹窗显示，remainingLastFours 让表单收缩到未成功部分，
      // 用户直接重试不会把已创建的卡再建一遍。
      formError.value = {
        message: t('creditCards.batchPartialFailed', {
          n: batch.created,
          m: batch.created + 1,
          reason
        }),
        remainingLastFours: batch.remainingLastFours || []
      }
    } else {
      formError.value = error.response?.data?.detail || t('common.networkError')
    }
  }
}

function requestDelete(card) {
  confirm.open({
    title: t('creditCards.deleteTitle'),
    message: t('creditCards.deleteMessage', { name: card.display_name }),
    danger: true,
    onConfirm: async () => {
      await remove(card)
      if (detailTarget.value?.id === card.id) detailTarget.value = null
      // 删卡后账单转孤立但仍在待还口径内；刷新汇总保持一致
      await refreshOutstanding().catch(() => {})
      toast(t('creditCards.deleted'))
    }
  })
}

// 卡片上「标记已还款」：把该卡全部未标记的勾稽通过账单（含历史各期）一次标记。
// 需确认——这决定待还总额是否剔除，误触会掩盖真实欠款。
// 文案按账单月份列出（「26年8月账单」）；有月份缺失的账单时明确补上笔数，
// 保证确认范围 = 实际标记范围。
async function requestMarkRepaid(card) {
  const entry = outstandingPerCard.value.get(card.id)
  const amount = entry ? formatAmount(entry.total_due) : ''
  const cyclesText = buildScopeText(entry)
  confirm.open({
    title: t('creditCards.markRepaidTitle'),
    message: t('creditCards.markRepaidMessage', { name: card.display_name, cycles: cyclesText, amount }),
    confirmLabel: t('creditCards.markRepaid'),
    onConfirm: async () => {
      try {
        await markCardRepaid(card)
        toast(t('creditCards.markRepaidDone', { name: card.display_name, cycles: cyclesText }))
      } catch {
        toast(t('creditCards.markRepaidFailed'))
      }
    }
  })
}

onMounted(() => {
  load()
  // 汇总失败要响亮：置 outstandingError 展示重试入口，不伪装成 0 待还
  refreshOutstanding().catch(() => {})
})
</script>

<style scoped>
.credit-cards-page { min-width: 0; }
.cards-hero { position: relative; display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 16px; padding: 22px 24px; border: 1px solid var(--border); border-radius: var(--radius); background: linear-gradient(180deg, color-mix(in srgb, var(--primary-soft) 72%, var(--surface)), var(--surface)); box-shadow: var(--shadow); }
.cards-hero::after { content: ''; position: absolute; inset: 0 auto 0 0; width: 4px; background: linear-gradient(180deg, var(--signal-cyan), var(--primary)); }
.hero-copy, .hero-actions { position: relative; z-index: 1; min-width: 0; }
.hero-kicker { display: inline-flex; align-items: center; gap: 8px; color: var(--primary); font-size: 12px; font-weight: 750; letter-spacing: .12em; }
.cards-hero h1 { margin: 8px 0 6px; }
.cards-hero p { max-width: 52ch; margin: 0; color: var(--text-soft); font-size: 14px; line-height: 1.6; }
.hero-actions { display: flex; flex: 0 0 auto; flex-direction: column; align-items: flex-end; gap: 12px; }
.hero-actions span { color: var(--text-soft); font-size: 13px; font-weight: 700; }
.cards-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
.empty-state { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 34px 22px; text-align: center; border-style: dashed; }
.empty-state h2 { margin: 5px 0 0; font-size: 17px; }
.empty-state p { max-width: 42ch; margin: 0 0 8px; color: var(--text-soft); font-size: 13px; line-height: 1.6; }
.empty-card { position: relative; width: 58px; height: 39px; border: 1px dashed color-mix(in srgb, var(--primary) 50%, var(--border)); border-radius: 12px; background: var(--surface-2); transform: rotate(-4deg); }
.empty-card span { position: absolute; right: 8px; bottom: 8px; width: 18px; height: 3px; border-radius: 999px; background: color-mix(in srgb, var(--signal-cyan) 65%, var(--primary)); }
.page-disclaimer { display: flex; gap: 11px; margin-top: 18px; padding: 14px 16px; border: 1px solid color-mix(in srgb, var(--warning) 32%, var(--border)); border-radius: 14px; background: color-mix(in srgb, var(--warning) 6%, var(--surface)); }
/* 最长免息期 stat tile（插槽传入，覆盖 scoped 隔离）：可点击 + 信号色强调 */
.page-disclaimer > span { display: flex; width: 24px; height: 24px; flex: 0 0 24px; align-items: center; justify-content: center; border-radius: 999px; background: color-mix(in srgb, var(--warning) 16%, var(--surface)); color: var(--warning-text); font-weight: 900; }
.page-disclaimer strong { color: var(--warning-text); font-size: 12px; }
.page-disclaimer p, .delete-copy { margin: 4px 0 0; color: var(--text-soft); font-size: 12px; line-height: 1.6; }
.delete-error { color: var(--danger-text); font-size: 13px; }
@media (max-width: 900px) {
  .cards-grid { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .cards-hero { align-items: stretch; flex-direction: column; padding: 18px; }
  .hero-actions { align-items: stretch; }
  .hero-actions .btn { width: 100%; }
}
@media (max-width: 390px) {
  .cards-hero { padding: 16px; }
  .page-disclaimer { padding: 12px; }
}
@media (prefers-reduced-motion: reduce) {
  .empty-card { transform: none; }
}
</style>
