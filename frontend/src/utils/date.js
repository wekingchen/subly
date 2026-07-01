const DAY_MS = 86400000
const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T\s])/

export function parseLocalDate(value) {
  if (!value) return null
  if (value instanceof Date) {
    const time = value.getTime()
    return Number.isNaN(time) ? null : new Date(time)
  }
  const m = typeof value === 'string' && value.match(DATE_ONLY_RE)
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function toISODate(value) {
  const date = parseLocalDate(value)
  if (!date) return ''
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function daysInMonth(year, monthIndex) {
  return new Date(year, monthIndex + 1, 0).getDate()
}

function addMonths(date, months) {
  const source = parseLocalDate(date) || new Date()
  const day = source.getDate()
  const target = new Date(source)
  target.setDate(1)
  target.setMonth(target.getMonth() + months)
  const dim = daysInMonth(target.getFullYear(), target.getMonth())
  target.setDate(Math.min(day, dim))
  return target
}

export function addCycleDate(dateOrString, cycle, count) {
  const n = Math.max(1, Number(count) || 1)
  const date = parseLocalDate(dateOrString) || new Date()
  if (cycle === 'day') { date.setDate(date.getDate() + n); return date }
  if (cycle === 'week') { date.setDate(date.getDate() + n * 7); return date }
  if (cycle === 'year') return addMonths(date, n * 12)
  return addMonths(date, n)
}

export function daysLeft(valueOrItem, options = {}) {
  const field = options.field || 'next_renewal_date'
  const value = valueOrItem && typeof valueOrItem === 'object' && !(valueOrItem instanceof Date)
    ? valueOrItem[field]
    : valueOrItem
  const target = parseLocalDate(value)
  if (!target) return null
  const now = parseLocalDate(options.now) || new Date()
  return Math.ceil((target - now) / DAY_MS)
}
