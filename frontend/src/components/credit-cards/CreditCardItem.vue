<template>
  <article class="credit-card card" :class="{ inactive: !card.is_active, 'is-best': highlight }">
    <div class="card-head">
      <div class="card-glyph" aria-hidden="true">
        <CreditCardBrandBadge :bank-name="card.bank_name" />
      </div>
      <div class="card-title">
        <div class="card-name">{{ card.display_name }}</div>
        <div class="card-bank">{{ card.bank_name }}<template v-if="card.last_four"> ···· {{ card.last_four }}</template></div>
      </div>
      <span class="status-tag" :class="card.is_active ? 'active' : 'inactive-tag'">
        {{ card.is_active ? t('creditCards.active') : t('creditCards.inactive') }}
      </span>
      <!-- 操作收敛：编辑/删除收进右上「⋯」，卡片主区只留核心操作（与订阅卡片同一交互语言） -->
      <button
        ref="moreBtnRef"
        type="button"
        class="card-more"
        :aria-label="`${card.display_name}：${t('common.actions')}`"
        :aria-expanded="menuOpen ? 'true' : 'false'"
        aria-haspopup="menu"
        :disabled="disabled"
        @click.stop="toggleMenu"
      >⋯</button>
    </div>

    <CreditCardCycleTrack :card="card" />

    <!-- 待还信息行：用户最关注的金额与逾期状态；名义日/提醒/额度等细节在详情。
         负合计（溢缴款/多还）显示「账上有富余」而非负数；金额展示取绝对值。
         净额富余但仍有正金额逾期欠款时，红标补欠款额——别让「富余」掩盖真欠款 -->
    <div v-if="outstandingEntry" class="outstanding-line" :class="{ 'is-surplus': outstandingEntry.is_surplus }">
      <span class="outstanding-label">{{ outstandingEntry.is_surplus ? t('creditCards.surplusOfCard') : t('creditCards.outstandingOfCard') }}</span>
      <span class="outstanding-amt mono-data" :class="{ 'is-overdue': outstandingEntry.max_overdue_days > 0 }">{{ formatLimit(Math.abs(outstandingEntry.total_due)) }}</span>
      <span v-if="outstandingEntry.is_surplus" class="surplus-tag">{{ t('creditCards.surplusTag') }}</span>
      <span v-if="outstandingEntry.max_overdue_days > 0" class="overdue-tag">
        {{ outstandingEntry.is_surplus
          ? t('creditCards.overdueWithAmount', { n: outstandingEntry.max_overdue_days, amount: formatLimit(outstandingEntry.overdue_amount || 0) })
          : t('creditCards.overdueDays', { n: outstandingEntry.max_overdue_days }) }}
      </span>
    </div>

    <div class="card-actions">
      <!-- 纯富余（净额为负且无逾期欠款）没有需要做的还款操作，不提供按钮——
           富余留在净额里继续抵扣后续账单（与银行溢缴款滚存一致）；
           净额富余但另有逾期欠款时保留（标记已结清一并清掉） -->
      <button
        v-if="outstandingEntry && (!outstandingEntry.is_surplus || outstandingEntry.overdue_amount > 0)"
        type="button"
        class="btn ghost sm repay-btn"
        :disabled="disabled"
        :title="outstandingEntry.is_surplus
          ? t('creditCards.markRepaidSurplusHint', { cycles: buildRepaidScopeText(outstandingEntry, t) })
          : t('creditCards.markRepaidHint', { cycles: buildRepaidScopeText(outstandingEntry, t) })"
        @click="$emit('mark-repaid', card)"
      >
        <span aria-hidden="true">✓</span> {{ outstandingEntry.is_surplus ? t('creditCards.markRepaidSurplus') : t('creditCards.markRepaid') }}
        <span class="repay-amt mono-data">{{ formatLimit(Math.abs(outstandingEntry.total_due)) }}</span>
      </button>
      <button type="button" class="btn ghost sm" :disabled="disabled" @click="$emit('view', card)">{{ t('creditCards.viewDetails') }}</button>
    </div>

    <!-- 操作菜单：Teleport 到 body（卡片 overflow:hidden 会裁剪 absolute 子元素）；
         fixed 定位锚在「⋯」按钮，下方空间不足翻上方。点遮罩/Escape/选单项关闭 -->
    <Teleport to="body">
      <div v-if="menuOpen" class="cc-menu-backdrop" @click="closeMenu"></div>
      <div
        v-if="menuOpen"
        ref="menuRef"
        class="cc-menu"
        role="menu"
        :aria-label="t('common.actions')"
        :style="menuStyle"
        @click.stop
      >
        <button type="button" class="cc-menu-item" role="menuitem" @click="onMenuAction('edit')">
          <span aria-hidden="true">✎</span>
          <span>{{ t('creditCards.edit') }}</span>
        </button>
        <button type="button" class="cc-menu-item danger" role="menuitem" @click="onMenuAction('delete')">
          <span aria-hidden="true">×</span>
          <span>{{ t('creditCards.delete') }}</span>
        </button>
      </div>
    </Teleport>
  </article>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import CreditCardBrandBadge from './CreditCardBrandBadge.vue'
import CreditCardCycleTrack from './CreditCardCycleTrack.vue'
import { buildRepaidScopeText } from '../../utils/creditCardDates'

const props = defineProps({
  card: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  highlight: { type: Boolean, default: false },
  // 该卡未标记还款的汇总 { total_due, count, cycles, overdue_cycles, max_overdue_days }；
  // 无未还账单为 null（待还行与按钮隐藏）
  outstandingEntry: { type: Object, default: null }
})

const emit = defineEmits(['view', 'edit', 'delete', 'mark-repaid'])
const { t } = useI18n()

// 额度仅作展示记录：千分位整数（有小数保留两位），不带币种符号——币种跟随用户基准币。
function formatLimit(value) {
  const n = Number(value)
  return Number.isInteger(n) ? n.toLocaleString('zh-CN') : n.toFixed(2)
}

// 「⋯」菜单：fixed 定位（Teleport 后脱离卡片），右对齐触发钮，空间不足翻上方。
// 打开期间才挂全局监听（focusin/scroll/resize/keydown），关闭即卸——
// Tab/焦点逃逸会让菜单与其它弹窗错层，直接关菜单最可靠；滚动会脱锚同理。
const menuOpen = ref(false)
const menuStyle = ref({})
const moreBtnRef = ref(null)
const menuRef = ref(null)

const MENU_GAP = 6
const MENU_EDGE = 8
const MENU_WIDTH = 150

function toggleMenu() {
  if (menuOpen.value) closeMenu()
  else openMenu()
}

function openMenu() {
  menuOpen.value = true
  nextTick(positionMenu)
  document.addEventListener('keydown', onDocKeydown)
  document.addEventListener('focusin', onDocFocusIn, true)
  document.addEventListener('scroll', onDocScroll, true)
  window.addEventListener('resize', onDocScroll)
}

function positionMenu() {
  const anchor = moreBtnRef.value
  if (!anchor || typeof window === 'undefined') return
  const r = anchor.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  const left = Math.max(MENU_EDGE, Math.min(r.right - MENU_WIDTH, vw - MENU_WIDTH - MENU_EDGE))
  const below = vh - r.bottom - MENU_GAP - MENU_EDGE
  if (below < 120 && r.top > below) {
    menuStyle.value = { left: `${left}px`, bottom: `${vh - r.top + MENU_GAP}px` }
  } else {
    menuStyle.value = { left: `${left}px`, top: `${r.bottom + MENU_GAP}px` }
  }
  menuRef.value?.querySelector('button')?.focus()
}

function closeMenu(options = {}) {
  if (!menuOpen.value) return
  menuOpen.value = false
  document.removeEventListener('keydown', onDocKeydown)
  document.removeEventListener('focusin', onDocFocusIn, true)
  document.removeEventListener('scroll', onDocScroll, true)
  window.removeEventListener('resize', onDocScroll)
  // refocus=false：调用方马上要自己设置焦点（如菜单项动作先回焦再 emit）
  if (options.refocus !== false) moreBtnRef.value?.focus()
}

function onMenuAction(action) {
  // 先关菜单并回焦「⋯」：父级弹窗（AppModal）记录前一焦点用它，
  // 取消弹窗后键盘用户才能回到原卡片位置（焦点不能落在将卸载的菜单项上）
  closeMenu({ refocus: true })
  emit(action, props.card)
}

function onDocKeydown(event) {
  if (event.key === 'Escape') {
    closeMenu()
  } else if (event.key === 'Tab') {
    // Tab 会把焦点送出菜单（Teleport 到 body 末尾，无可圈住的后继），
    // 与其让焦点逃到遮罩下其它控件再错层，直接关菜单并把焦点交回触发钮
    closeMenu()
  }
}

function onDocFocusIn(event) {
  // 焦点以任何方式离开菜单（点外、程序设焦）都视为放弃菜单
  if (menuOpen.value && !menuRef.value?.contains(event.target) && event.target !== moreBtnRef.value) {
    closeMenu({ refocus: false })
  }
}

function onDocScroll() {
  // fixed 菜单不跟随滚动/视口变化，脱锚后展示位置会误导操作对象——直接关
  closeMenu({ refocus: false })
}

onBeforeUnmount(() => {
  closeMenu({ refocus: false })
})
</script>

<style scoped>
.credit-card { position: relative; display: flex; min-width: 0; flex-direction: column; gap: 12px; overflow: hidden; }
.credit-card::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 4px; background: linear-gradient(180deg, var(--signal-cyan), var(--primary)); }
.credit-card.inactive { opacity: .68; border-style: dashed; }
.credit-card.inactive::before { background: var(--text-soft); opacity: .5; }
.card-head { display: flex; min-width: 0; align-items: center; gap: 9px; }
.card-glyph { position: relative; display: flex; width: 44px; height: 34px; flex: 0 0 44px; align-items: stretch; padding: 0; border: 1px solid color-mix(in srgb, var(--primary) 30%, var(--border)); border-radius: 10px; overflow: hidden; box-shadow: 0 6px 16px color-mix(in srgb, var(--primary) 18%, transparent); }
.card-title { min-width: 0; flex: 1; }
.card-name { overflow: hidden; font-size: 16px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.card-bank { margin-top: 3px; color: var(--text-soft); font-size: 12px; overflow-wrap: anywhere; }
.status-tag { flex: 0 0 auto; padding: 4px 9px; border-radius: 999px; font-size: 11px; font-weight: 750; }
.status-tag.active { background: color-mix(in srgb, var(--success) 11%, var(--surface)); color: var(--success-text); }
.status-tag.inactive-tag { background: var(--surface-2); color: var(--text-soft); }
/* 「⋯」入口：与订阅卡片 card-more 同一交互语言（圆形透明 hover） */
.card-more { display: inline-flex; flex-shrink: 0; align-items: center; justify-content: center; width: var(--tap-size); height: var(--tap-size); margin-right: -6px; border: none; border-radius: 999px; background: transparent; color: var(--text-soft); cursor: pointer; font-size: 20px; line-height: 1; transition: background .15s ease, color .15s ease; }
.card-more:hover { background: var(--surface-2); color: var(--text); }
.card-more:focus-visible { outline: 2px solid var(--primary); outline-offset: 1px; }
.outstanding-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; padding: 9px 12px; border: 1px solid color-mix(in srgb, var(--warning) 32%, var(--border)); border-radius: 10px; background: color-mix(in srgb, var(--warning) 6%, var(--surface)); }
.outstanding-line .is-overdue, .outstanding-line.is-overdue .outstanding-amt { color: var(--danger-text); }
/* 富余（负合计）：绿色基调——不是欠款，是多还/溢缴款 */
.outstanding-line.is-surplus { border-color: color-mix(in srgb, var(--success) 32%, var(--border)); background: color-mix(in srgb, var(--success) 6%, var(--surface)); }
.outstanding-line.is-surplus .outstanding-amt { color: var(--success-text); }
.surplus-tag { margin-left: auto; padding: 2px 8px; border-radius: 999px; background: color-mix(in srgb, var(--success) 13%, transparent); color: var(--success-text); font-size: 11px; font-weight: 750; }
.outstanding-label { color: var(--text-soft); font-size: 12px; font-weight: 750; }
.outstanding-amt { font-size: 18px; font-weight: 800; color: var(--warning-text); }
.overdue-tag { margin-left: auto; padding: 2px 8px; border-radius: 999px; background: color-mix(in srgb, var(--danger) 13%, transparent); color: var(--danger-text); font-size: 11px; font-weight: 750; }
.credit-card.is-best { border-color: color-mix(in srgb, var(--signal-cyan) 55%, var(--border)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--signal-cyan) 30%, transparent), 0 8px 22px color-mix(in srgb, var(--signal-cyan) 14%, transparent); }
.credit-card.is-best::before { background: linear-gradient(180deg, var(--signal-cyan), var(--primary)); box-shadow: 0 0 12px color-mix(in srgb, var(--signal-cyan) 55%, transparent); }
.card-actions { display: flex; flex-direction: column; gap: 8px; margin-top: auto; padding-top: 2px; }
.repay-btn { color: var(--success-text); border-color: color-mix(in srgb, var(--success) 38%, var(--border)); }
.repay-amt { margin-left: 4px; font-weight: 800; }
/* 操作菜单（Teleport 到 body，fixed 定位；样式参数与订阅 ActionMenuContent 一致） */
.cc-menu-backdrop { position: fixed; inset: 0; z-index: 90; }
.cc-menu { position: fixed; z-index: 91; min-width: 150px; padding: 6px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: var(--shadow-lg); }
.cc-menu-item { display: flex; width: 100%; align-items: center; gap: 10px; padding: 10px 12px; border: 0; border-radius: 8px; background: none; color: var(--text); font: inherit; font-weight: 650; cursor: pointer; text-align: left; }
.cc-menu-item:hover { background: var(--surface-2); }
.cc-menu-item.danger { color: var(--danger-text); }
.cc-menu-item:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
@media (hover: hover) and (pointer: fine) {
  .credit-card { transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease; }
  .credit-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
}
@media (max-width: 420px) {
  .card-head { align-items: flex-start; flex-wrap: wrap; }
  .card-title { flex-basis: calc(100% - 56px); }
  .status-tag { margin-left: 55px; }
  .card-more { margin-left: auto; }
  .card-name { white-space: normal; }
}
@media (prefers-reduced-motion: reduce) {
  .credit-card { transition: none; }
}
</style>
