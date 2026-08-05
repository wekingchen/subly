import { toISODate } from './date'
import { amountOf } from './money'
import { expandRenewalsInRange } from './recurrence'

export const TREND_MONTH_OPTIONS = [3, 6, 12]

export function normalizeTrendMonths(value) {
  const months = Number(value)
  return TREND_MONTH_OPTIONS.includes(months) ? months : 6
}

export function monthKeyAt(value, offset = 0) {
  const d = value instanceof Date ? value : new Date(value)
  const target = new Date(d.getFullYear(), d.getMonth() + offset, 1)
  return `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}`
}

export function buildFutureTrend(subscriptions, months, { now = new Date() } = {}) {
  const count = normalizeTrendMonths(months)
  const startISO = toISODate(now)
  const end = new Date(now.getFullYear(), now.getMonth() + count, 0)
  const endISO = toISODate(end)
  const events = expandRenewalsInRange(subscriptions || [], startISO, endISO, { includeHidden: true })
  const byMonth = new Map()

  for (let offset = 0; offset < count; offset += 1) {
    byMonth.set(monthKeyAt(now, offset), 0)
  }
  for (const event of events) {
    const month = (event.occurrence_date || '').slice(0, 7)
    if (!byMonth.has(month)) continue
    byMonth.set(month, byMonth.get(month) + amountOf(event))
  }

  return [...byMonth.entries()].map(([month, amount]) => ({
    month,
    amount: Math.round(amount * 100) / 100
  }))
}
