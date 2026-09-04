import { describe, expect, it } from 'vitest'
import { creditCardCalendarEvents, groupCalendarEventsByDate } from './calendarEvents'

const card = {
  id: 12,
  display_name: '主卡',
  due_day: 31,
  is_active: true,
  show_in_calendar: true
}

describe('creditCardCalendarEvents', () => {
  it('按名义月份锚定月末且不链式漂移', () => {
    const events = creditCardCalendarEvents(
      [card],
      new Date(2024, 0, 1),
      new Date(2024, 3, 30)
    )
    expect(events.map((event) => event.occurrence_date)).toEqual([
      '2024-01-31',
      '2024-02-29',
      '2024-03-31',
      '2024-04-30'
    ])
    expect(events.every((event) => event.kind === 'credit_card')).toBe(true)
    expect(events.every((event) => event.amount == null)).toBe(true)
  })

  it('排除停用或隐藏卡片并可与其他来源分组', () => {
    const events = creditCardCalendarEvents([
      card,
      { ...card, id: 13, is_active: false },
      { ...card, id: 14, show_in_calendar: false }
    ], new Date(2024, 0, 1), new Date(2024, 0, 31))
    const grouped = groupCalendarEventsByDate(events)
    expect(events).toHaveLength(1)
    expect(grouped.get('2024-01-31')).toHaveLength(1)
  })

  it('排除已还款界线覆盖的期次（含界线当天），之后期次保留', () => {
    const events = creditCardCalendarEvents(
      [{ ...card, repaid_through_due: '2024-02-29' }],
      new Date(2024, 0, 1),
      new Date(2024, 3, 30)
    )
    // 1/31 与 2/29（界线含当天）已还 → 不出现；3/31 起保留
    expect(events.map((event) => event.occurrence_date)).toEqual([
      '2024-03-31',
      '2024-04-30'
    ])
  })

  it('详情 raw 携带所点击周期的日期，而非卡片当前下一期', () => {
    const cards = [{
      id: 12,
      display_name: '主卡',
      statement_day: 10,
      due_day: 28,
      is_active: true,
      show_in_calendar: true,
      next_due_date: '2026-08-28'
    }]
    const events = creditCardCalendarEvents(cards, new Date(2027, 1, 1), new Date(2027, 1, 28))
    expect(events).toHaveLength(1)
    const detail = events[0].raw
    expect(detail.next_due_date).toBe('2027-02-28')
    // due_day > statement_day：账单日与还款日同一名义月份。
    expect(detail.next_statement_date).toBe('2027-02-10')
    expect(detail.statement_to_due_days).toBe(18)
  })

  it('due_day <= statement_day 时详情账单日落在前一名义月份', () => {
    const cards = [{
      id: 15,
      display_name: '跨月卡',
      statement_day: 25,
      due_day: 5,
      is_active: true,
      show_in_calendar: true
    }]
    const events = creditCardCalendarEvents(cards, new Date(2026, 8, 1), new Date(2026, 8, 30))
    const detail = events[0].raw
    expect(detail.next_due_date).toBe('2026-09-05')
    expect(detail.next_statement_date).toBe('2026-08-25')
    expect(detail.statement_to_due_days).toBe(11)
  })

  it('1 月还款日的详情账单日回退到上一年 12 月（跨年分支）', () => {
    const cards = [{
      id: 16,
      display_name: '跨年卡',
      statement_day: 20,
      due_day: 5,
      is_active: true,
      show_in_calendar: true
    }]
    const events = creditCardCalendarEvents(cards, new Date(2027, 0, 1), new Date(2027, 0, 31))
    const detail = events[0].raw
    expect(detail.next_due_date).toBe('2027-01-05')
    expect(detail.next_statement_date).toBe('2026-12-20')
    expect(detail.statement_to_due_days).toBe(16)
  })

  it('statement_day 为 31 时详情账单日在 2 月锚定到月末', () => {
    const cards = [{
      id: 17,
      display_name: '月末卡',
      statement_day: 31,
      due_day: 10,
      is_active: true,
      show_in_calendar: true
    }]
    // 平年 2 月：还款日 3 月 10 日对应账单日 2 月 28 日（闰年应锚定 29 日）。
    const events = creditCardCalendarEvents(cards, new Date(2027, 2, 1), new Date(2027, 2, 31))
    const detail = events[0].raw
    expect(detail.next_due_date).toBe('2027-03-10')
    expect(detail.next_statement_date).toBe('2027-02-28')

    const leapEvents = creditCardCalendarEvents(cards, new Date(2024, 2, 1), new Date(2024, 2, 31))
    expect(leapEvents[0].raw.next_statement_date).toBe('2024-02-29')
  })

  it('statement_day = due_day = 31 时账单日属于前一名义月份且锚定月末', () => {
    const cards = [{
      id: 18,
      display_name: '同日卡',
      statement_day: 31,
      due_day: 31,
      is_active: true,
      show_in_calendar: true
    }]
    const events = creditCardCalendarEvents(cards, new Date(2024, 3, 1), new Date(2024, 3, 30))
    const detail = events[0].raw
    expect(detail.next_due_date).toBe('2024-04-30')
    // due_day <= statement_day：账单日回退到 3 月 31 日。
    expect(detail.next_statement_date).toBe('2024-03-31')
    expect(detail.statement_to_due_days).toBe(30)
  })

  it('同一银行同还款日的多卡合并为一条「XX银行信用卡」', () => {
    const events = creditCardCalendarEvents([
      { ...card, id: 21, display_name: '山姆联名卡', bank_name: '民生银行' },
      { ...card, id: 22, display_name: 'VISA标准白金卡', bank_name: '民生银行' },
      { ...card, id: 23, display_name: '他行卡', bank_name: '招商银行' }
    ], new Date(2024, 0, 1), new Date(2024, 0, 31))
    // 民生两张同日 → 合并一条；他行单独一条
    expect(events).toHaveLength(2)
    const merged = events.find((event) => event.cards_count === 2)
    expect(merged.name).toBe('民生银行信用卡')
    expect(merged.key).toBe('credit-card:brand:cmbc|2024-01-31')
    // 单卡保持卡名
    const single = events.find((event) => event.cards_count === 1)
    expect(single.name).toBe('他行卡')
    // 点击打开该组第一张卡的详情
    expect(merged.raw.display_name).toBe('山姆联名卡')
  })

  it('未收录银行的 raw 分组归一大小写（HSBC 与 hsbc 同组）', () => {
    const events = creditCardCalendarEvents([
      { ...card, id: 51, display_name: '汇丰A', bank_name: 'HSBC' },
      { ...card, id: 52, display_name: '汇丰B', bank_name: 'hsbc' }
    ], new Date(2024, 0, 1), new Date(2024, 0, 31))
    expect(events).toHaveLength(1)
    expect(events[0].cards_count).toBe(2)
  })

  it('事件图标用所属银行官方 logo；未收录银行回退 null（💳 兜底）', () => {
    const events = creditCardCalendarEvents([
      { ...card, id: 61, display_name: '招行卡', bank_name: '招商银行' },
      { ...card, id: 62, display_name: '汇丰卡', bank_name: 'HSBC' }
    ], new Date(2024, 0, 1), new Date(2024, 0, 31))
    const ccb = events.find((event) => event.sourceId === 61)
    const hsbc = events.find((event) => event.sourceId === 62)
    // 与卡片徽标同源：内置图标库 slug（cmbchina.com → cmbchina_com）。
    // 官方 logo 抓取失败时后端返回生成的银行首字字标（HTTP 200）；
    // 未收录银行 icon 置 null，由 ServiceIcon 回退 💳
    expect(ccb.icon).toBe('/api/icons/library/cmbchina_com')
    expect(hsbc.icon).toBeNull()
  })

  it('银行名称别名（「民生」「中国民生银行」）与「民生银行」合并为同组', () => {
    const events = creditCardCalendarEvents([
      { ...card, id: 41, display_name: '山姆联名卡', bank_name: '民生' },
      { ...card, id: 42, display_name: 'VISA标准白金卡', bank_name: '中国民生银行' },
      { ...card, id: 43, display_name: '标准卡', bank_name: '民生银行' }
    ], new Date(2024, 0, 1), new Date(2024, 0, 31))
    expect(events).toHaveLength(1)
    expect(events[0].cards_count).toBe(3)
    // 分组标题用规范银行名（brand.name），不沿用用户手填变体
    expect(events[0].name).toBe('民生银行信用卡')
  })

  it('同银行但已还款界线不同的卡不合并（各自独立展示）', () => {
    // 民生卡 A 已还至 1 月底（1 月期次消失），卡 B 未标记仍显示——
    // 若无条件按银行合并会把 B 的还款日也吞掉
    const events = creditCardCalendarEvents([
      { ...card, id: 31, display_name: '民生A', bank_name: '民生银行', repaid_through_due: '2024-01-31' },
      { ...card, id: 32, display_name: '民生B', bank_name: '民生银行' }
    ], new Date(2024, 0, 31), new Date(2024, 0, 31))
    expect(events).toHaveLength(1)
    expect(events[0].cards_count).toBe(1)
    expect(events[0].name).toBe('民生B')
  })
})
