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
