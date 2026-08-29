import { parseLocalDate, toISODate } from './date'
import { expandRenewalsInRange } from './recurrence'

function anchorMonthDay(year, month, nominalDay) {
  const lastDay = new Date(year, month + 1, 0).getDate()
  return new Date(year, month, Math.min(Number(nominalDay), lastDay))
}

export function subscriptionCalendarEvents(subscriptions, start, end) {
  return expandRenewalsInRange(subscriptions, start, end).map((event) => ({
    ...event,
    key: `subscription:${event.id}`,
    kind: 'subscription',
    sourceId: event.occurrence_origin_id ?? Number(String(event.id).split(':')[0]),
    sourceLabel: '订阅'
  }))
}

// 与后端 credit_card_rules.statement_date_for_due 同一套名义日配对规则：
// due_day <= statement_day 时账单日在前一名义月份，避免零天周期。
function statementDateForOccurrence(occurrence, card) {
  const dueDay = Number(card.due_day)
  const statementDay = Number(card.statement_day)
  let year = occurrence.getFullYear()
  let month = occurrence.getMonth()
  if (dueDay <= statementDay) {
    if (month === 0) {
      year -= 1
      month = 11
    } else {
      month -= 1
    }
  }
  return anchorMonthDay(year, month, statementDay)
}

function occurrenceDetail(card, occurrence) {
  const statement = statementDateForOccurrence(occurrence, card)
  const span = Math.round((occurrence - statement) / 86400000)
  return {
    ...card,
    next_due_date: toISODate(occurrence),
    next_statement_date: toISODate(statement),
    statement_to_due_days: span
  }
}

export function creditCardCalendarEvents(cards, start, end) {
  const rangeStart = parseLocalDate(start)
  const rangeEnd = parseLocalDate(end)
  if (!rangeStart || !rangeEnd || rangeEnd < rangeStart) return []
  const events = []
  let year = rangeStart.getFullYear()
  let month = rangeStart.getMonth()
  const endYear = rangeEnd.getFullYear()
  const endMonth = rangeEnd.getMonth()
  while (year < endYear || (year === endYear && month <= endMonth)) {
    for (const card of cards || []) {
      if (!card?.is_active || card.show_in_calendar === false) continue
      const occurrence = anchorMonthDay(year, month, card.due_day)
      if (occurrence < rangeStart || occurrence > rangeEnd) continue
      const occurrenceDate = toISODate(occurrence)
      events.push({
        id: `credit-card:${card.id}:${occurrenceDate}`,
        key: `credit-card:${card.id}:${occurrenceDate}`,
        kind: 'credit_card',
        sourceId: card.id,
        sourceLabel: '信用卡',
        name: card.display_name,
        icon: null,
        occurrence_date: occurrenceDate,
        next_renewal_date: occurrenceDate,
        amount: null,
        currency: null,
        // 详情弹窗展示的是被点击的那一期，而非卡片"今天"的下一期；
        // raw 携带 occurrence 专属的账单日/还款日/间隔。
        raw: occurrenceDetail(card, occurrence)
      })
    }
    if (month === 11) {
      year += 1
      month = 0
    } else {
      month += 1
    }
  }
  return events
}

export function groupCalendarEventsByDate(events) {
  const grouped = new Map()
  for (const event of events || []) {
    const key = event.occurrence_date || event.next_renewal_date
    if (!key) continue
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key).push(event)
  }
  return grouped
}
