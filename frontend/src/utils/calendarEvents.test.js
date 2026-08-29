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
})
