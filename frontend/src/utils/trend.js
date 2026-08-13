import { toISODate } from './date'
import { amountOf, formatMoney } from './money'
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

export function buildTrendViewModel(history, future, { baseCurrency = 'CNY', currentMonth = '' } = {}) {
  const byMonth = new Map()
  const ensure = (month) => {
    if (!byMonth.has(month)) byMonth.set(month, { month, history: 0, future: 0 })
    return byMonth.get(month)
  }
  for (const row of history || []) ensure(row.month).history += Number(row.amount) || 0
  for (const row of future || []) ensure(row.month).future += Number(row.amount) || 0

  const rows = [...byMonth.values()].sort((a, b) => a.month.localeCompare(b.month))
  const max = Math.max(1, ...rows.map((row) => row.history + row.future))
  let previousYear = ''

  return rows.map((row) => {
    const [year, month] = row.month.split('-')
    const total = row.history + row.future
    const showYear = year !== previousYear
    previousYear = year
    const historyText = formatMoney(row.history, baseCurrency)
    const futureText = formatMoney(row.future, baseCurrency)
    const totalText = formatMoney(total, baseCurrency)
    return {
      key: row.month,
      month: row.month,
      label: month,
      yearLabel: showYear ? year : '',
      current: row.month === currentMonth,
      history: row.history,
      future: row.future,
      total,
      historyHeight: row.history > 0 ? (row.history / max) * 100 : 0,
      futureHeight: row.future > 0 ? (row.future / max) * 100 : 0,
      historyText,
      futureText,
      totalText,
      ariaLabel: `${row.month}，历史付款：${historyText}，未来预计：${futureText}，合计：${totalText}`
    }
  })
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
