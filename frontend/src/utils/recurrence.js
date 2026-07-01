import { addCycleDate, parseLocalDate, toISODate } from './date'

const DAY_MS = 86400000
const GUARD = 2400

function normSub(sub) {
  return {
    ...sub,
    // 单次 occurrence 用「订阅 id : 日期」作为稳定 key，避免与原订阅重复 id
    id: `${sub.id}:${sub.occurrence_date}`,
    next_renewal_date: sub.occurrence_date,
    occurrence_date: sub.occurrence_date,
    occurrence_origin_id: sub.id
  }
}

function jumpCloseToRangeStart(cursor, sub, startTime) {
  const count = Math.max(1, Number(sub.cycle_count) || 1)
  const intervalDays = sub.cycle === 'day' ? count : sub.cycle === 'week' ? count * 7 : 0
  if (!intervalDays || cursor.getTime() >= startTime) return cursor
  const steps = Math.max(0, Math.floor((startTime - cursor.getTime()) / (intervalDays * DAY_MS)))
  return steps ? addCycleDate(cursor, sub.cycle, count * steps) : cursor
}

/**
 * 把周期订阅展开为「落在 [rangeStart, rangeEnd] 视图范围内」的续费事件列表。
 *
 * - 只展开 recurring、active、show_in_calendar、有合法 next_renewal_date 的订阅。
 * - 以 next_renewal_date 为当前业务基准向后投影，不回到 start_date 重算历史。
 * - end_date 非空时作为包含式截止：occurrence <= end_date 才输出。
 * - 输出对象把 next_renewal_date 替换为 occurrence 日期，方便复用 renewalStatus / amountOf 等。
 * - 不修改订阅本身、不写库。
 */
export function expandRenewalsInRange(subscriptions, rangeStart, rangeEnd) {
  const start = parseLocalDate(rangeStart)
  const end = parseLocalDate(rangeEnd)
  if (!start || !end) return []
  const startTime = start.getTime()
  const endTime = end.getTime()
  const out = []

  for (const sub of subscriptions || []) {
    if (!sub) continue
    if (sub.billing_type !== 'recurring') continue
    if (sub.is_active === false) continue
    if (sub.show_in_calendar === false) continue
    const base = parseLocalDate(sub.next_renewal_date)
    if (!base) continue
    const endLimit = parseLocalDate(sub.end_date)
    const endLimitTime = endLimit ? endLimit.getTime() : null
    if (endLimitTime !== null && endLimitTime < startTime) continue

    let cursor = jumpCloseToRangeStart(new Date(base), sub, startTime)
    let guard = 0
    while (cursor.getTime() < startTime && guard < GUARD) {
      cursor = addCycleDate(cursor, sub.cycle, sub.cycle_count)
      guard += 1
    }
    while (cursor.getTime() <= endTime && guard < GUARD) {
      if (endLimitTime !== null && cursor.getTime() > endLimitTime) break
      out.push(normSub({ ...sub, occurrence_date: toISODate(cursor) }))
      cursor = addCycleDate(cursor, sub.cycle, sub.cycle_count)
      guard += 1
    }
  }

  return out
}

export function groupRenewalEventsByDate(events) {
  const map = new Map()
  for (const ev of events || []) {
    const key = ev.occurrence_date
    if (!key) continue
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(ev)
  }
  return map
}
