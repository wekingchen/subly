import { parseLocalDate, toISODate } from './date'
import { expandRenewalsInRange } from './recurrence'
import { matchBankBrand } from './creditCardBanks'

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
    // 同一银行同还款日的多卡合并为一条「XX银行信用卡」（同一银行账单日/
    // 还款日规则一致，还款日必然相同，逐卡显示只会重复）；
    // 点击打开该组第一张卡的详情弹窗。
    // 分组身份用归一化银行标识（matchBankBrand 别名归一化：「民生」「中国
    // 民生银行」与「民生银行」同组）；未收录银行回退 trim 后的原始名。
    const byBank = new Map()
    for (const card of cards || []) {
      if (!card?.is_active || card.show_in_calendar === false) continue
      const occurrence = anchorMonthDay(year, month, card.due_day)
      if (occurrence < rangeStart || occurrence > rangeEnd) continue
      // 已还款的期次不再出现在日历（与后端 iCal 过滤同口径；
      // repaid_through_due 为名义还款日 ISO 字符串，含界线当天）
      if (card.repaid_through_due) {
        const repaidThrough = parseLocalDate(card.repaid_through_due)
        if (repaidThrough && occurrence <= repaidThrough) continue
      }
      const occurrenceDate = toISODate(occurrence)
      const brand = matchBankBrand(card.bank_name)
      const bankKey = brand
        ? `brand:${brand.key}`
        : `raw:${String(card.bank_name || '').trim().toLowerCase()}`  // 未收录银行也归一大小写（与 Stats 页 raw 键同口径）
      const groupKey = `${bankKey}|${occurrenceDate}`
      if (!byBank.has(groupKey)) byBank.set(groupKey, [])
      byBank.get(groupKey).push({ card, occurrence, occurrenceDate, brand })
    }
    for (const [groupKey, members] of byBank) {
      const { card, occurrence, occurrenceDate, brand } = members[0]
      const groupedName = members.length > 1
        ? `${brand ? brand.name : String(card.bank_name || '').trim()}信用卡`
        : card.display_name
      events.push({
        id: `credit-card:${card.id}:${occurrenceDate}`,
        key: `credit-card:${groupKey}`,
        kind: 'credit_card',
        sourceId: card.id,
        sourceLabel: '信用卡',
        name: groupedName,
        // 事件图标用所属银行 logo（与卡片徽标同源：内置图标库按 slug 提供、
        // 后端已消毒缓存）。官方 logo 抓取失败时，后端返回生成的银行首字
        // 字标（HTTP 200）；未收录银行 icon 置 null，接口或图片加载失败时
        // 由 ServiceIcon 回退 💳。
        icon: brand?.slug ? `/api/icons/library/${brand.slug}` : null,
        occurrence_date: occurrenceDate,
        next_renewal_date: occurrenceDate,
        amount: null,
        currency: null,
        cards_count: members.length,
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
