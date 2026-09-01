import { parseLocalDate } from './date'

function utcCalendarDay(value) {
  const date = parseLocalDate(value)
  if (!date) return null
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())
}

export function calendarDayDiff(from, to) {
  const start = utcCalendarDay(from)
  const end = utcCalendarDay(to)
  if (start == null || end == null) return null
  return Math.round((end - start) / 86400000)
}

export function formatCreditCardDate(value, locale = 'zh-CN') {
  const date = parseLocalDate(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', weekday: 'short' }).format(date)
}

export function creditCardCycle(card, today = new Date()) {
  const statementDate = card?.next_statement_date || null
  const dueDate = card?.next_due_date || null
  const rawDerivedSpan = card?.statement_to_due_days
  const derivedSpan = rawDerivedSpan == null || rawDerivedSpan === '' ? null : Number(rawDerivedSpan)
  const calculatedSpan = calendarDayDiff(statementDate, dueDate)
  const spanDays = Number.isFinite(derivedSpan) && derivedSpan >= 0 ? derivedSpan : calculatedSpan
  const daysFromStatement = calendarDayDiff(statementDate, today)
  const daysUntilDue = calendarDayDiff(today, dueDate)
  const valid = Boolean(statementDate && dueDate && spanDays != null && spanDays >= 0)
  const progress = !valid || daysFromStatement == null
    ? 0
    : spanDays === 0
      ? (daysFromStatement >= 0 ? 100 : 0)
      : Math.min(100, Math.max(0, (daysFromStatement / spanDays) * 100))
  const phase = !valid
    ? 'unknown'
    : daysFromStatement < 0
      ? 'before-statement'
      : daysUntilDue < 0
        ? 'overdue'
        : 'repayment-window'

  return {
    statementDate,
    dueDate,
    spanDays: valid ? spanDays : null,
    daysFromStatement,
    daysUntilDue,
    progress,
    phase,
    valid
  }
}

export function countUpcomingCreditCardDues(cards, today = new Date(), withinDays = 7) {
  return (cards || []).filter((card) => {
    if (!card?.is_active) return false
    const days = calendarDayDiff(today, card.next_due_date)
    return days != null && days >= 0 && days <= withinDays
  }).length
}

export function nearestCreditCardDue(cards, today = new Date()) {
  return (cards || [])
    .filter((card) => card?.is_active)
    .map((card) => ({ card, days: calendarDayDiff(today, card.next_due_date) }))
    .filter((entry) => entry.days != null && entry.days >= 0)
    .sort((a, b) => a.days - b.days)[0] || null
}

// 账单月份 → 「26年8月」：出账月即用户口中的账单月份（账单邮件命名口径）
export function formatCycleMonth(dateStr) {
  const date = parseLocalDate(dateStr)
  if (!date) return null
  return `${date.getFullYear() % 100}年${date.getMonth() + 1}月`
}

// 账单期显示名：「26年8月账单」。月份取 bill_period_end（有账单周期的银行）
// 或 statement_date（仅出账日的银行）；两者都缺回退 null，由调用方决定展示
export function statementCycleLabel(statement) {
  if (!statement) return null
  return formatCycleMonth(statement.bill_period_end || statement.statement_date)
}

// 批量标记范围的完整文案：「26年8月、26年7月账单及 1 笔未知月份账单」。
// 确认弹窗与按钮提示共用，保证展示范围 = 批量接口实际标记范围
// （该卡全部未还勾稽通过账单，含月份缺失的）。i18n 由调用方传入拼接词。
export function buildRepaidScopeText(entry, t) {
  const cycles = entry?.cycles || []
  const unknown = Number(entry?.unknown_cycle_count) || 0
  const parts = []
  if (cycles.length) parts.push(t('creditCards.statementCycleNames', { cycles: cycles.join('、') }))
  if (unknown) parts.push(t('creditCards.unknownCycleCount', { n: unknown }))
  if (!parts.length) parts.push(t('creditCards.outstandingCountOnly', { n: entry?.count || 0 }))
  return parts.join(t('creditCards.scopeJoin'))
}
