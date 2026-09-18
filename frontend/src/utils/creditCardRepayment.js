// 部分还款金额的输入解析与焦点行为（纯函数，可单测）。
// 金额按「分」整数比较，避免 0.1+0.7 < 0.8 的浮点误判（与后端口径一致）。

const AMOUNT_RE = /^\d{1,9}(\.\d{1,2})?$/

function toCents(n) {
  return Math.round(n * 100)
}

/**
 * 解析用户输入的还款金额。
 * @param {string} text 输入框原始文本
 * @param {number} remaining 剩余待还（元）
 * @returns {{ok: true, value: number} | {ok: false, error: 'invalid'|'exceeds'}}
 */
export function parseRepayAmount(text, remaining) {
  const trimmed = String(text ?? '').trim()
  if (!trimmed || !AMOUNT_RE.test(trimmed)) return { ok: false, error: 'invalid' }
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value <= 0) return { ok: false, error: 'invalid' }
  if (toCents(value) > toCents(remaining)) return { ok: false, error: 'exceeds' }
  return { ok: true, value }
}

/**
 * 焦点行为：值仍等于未改动的默认值时清空（placeholder 兜底「最高 X」）；
 * 已是用户输入则全选不销毁——比「每次 focus 清空」安全，意图不变。
 * @param {string} current 当前输入值
 * @param {string} defaultValue 打开弹窗时的默认值
 * @param {(el: HTMLInputElement) => void} applySelect 全选回调（DOM 副作用由调用方注入）
 * @returns {string} 新输入值
 */
export function nextAmountOnFocus(current, defaultValue, applySelect) {
  if (current === defaultValue) {
    return ''
  }
  applySelect?.()
  return current
}

/**
 * 账单剩余待还 = total_due − repaid_amount（按分整数防浮点误差，与后端口径一致）。
 * total_due 为 null/undefined（金额未知）返回 null。
 * @param {number|null} totalDue
 * @param {number|null} repaidAmount
 * @returns {number|null}
 */
export function statementRemainingAmount(totalDue, repaidAmount) {
  if (totalDue == null) return null
  const cents = Math.round(totalDue * 100) - Math.round((repaidAmount || 0) * 100)
  return cents / 100
}

/**
 * 剩余待还的裸数字文本（无千分位——逗号会破坏解析）：整数不带小数、
 * 非整数保留两位。
 * @param {number} n
 * @returns {string}
 */
export function formatAmountInput(n) {
  const num = Number(n) || 0
  return Number.isInteger(num) ? String(num) : num.toFixed(2)
}

/**
 * 账单列表加载守卫（纯函数，可单测）：全局模式（all=true）无条件加载；
 * 单卡模式必须有 cardId——两者都缺时不发请求（也不能隐式回退到全局）。
 * @param {boolean} all 全局模式
 * @param {number|null} cardId 单卡 id
 * @returns {boolean}
 */
export function shouldLoadStatements(all, cardId) {
  return Boolean(all) || cardId != null
}
