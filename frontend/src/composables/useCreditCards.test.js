import { describe, expect, it } from 'vitest'

import { buildCreditCardPayload } from './useCreditCards'

describe('buildCreditCardPayload', () => {
  it('sends only the writable API fields with normalized values', () => {
    const source = {
      id: 9,
      display_name: '  日常消费  ',
      bank_name: ' 招商银行 ',
      last_four: ' 1234 ',
      statement_day: '8',
      due_day: '26',
      remind_days_before: [3, 7],
      is_active: false,
      show_in_calendar: true,
      next_due_date: '2026-09-26'
    }

    expect(buildCreditCardPayload(source)).toEqual({
      display_name: '日常消费',
      bank_name: '招商银行',
      last_four: '1234',
      statement_day: 8,
      due_day: 26,
      remind_days_before: [3, 7],
      is_active: false,
      show_in_calendar: true
    })
  })

  it('parses a comma-separated reminder text into an integer array', () => {
    const payload = buildCreditCardPayload({ remind_days_before: '7, 3, 1, 0' })
    expect(payload.remind_days_before).toEqual([7, 3, 1, 0])
  })

  it('always sends remind_days_before as an array, never a scalar', () => {
    // 后端契约是 list[int]；标量会让保存必然 422。
    expect(Array.isArray(buildCreditCardPayload({}).remind_days_before)).toBe(true)
    expect(Array.isArray(buildCreditCardPayload({ remind_days_before: '' }).remind_days_before)).toBe(true)
  })

  it('allows an empty last_four so the backend stores it as null', () => {
    // 尾号是可选字段，前端不应强制填写。
    expect(buildCreditCardPayload({ last_four: '' }).last_four).toBe('')
    expect(buildCreditCardPayload({}).last_four).toBe('')
  })

  it('defaults switches to enabled but preserves explicit false', () => {
    expect(buildCreditCardPayload({}).is_active).toBe(true)
    expect(buildCreditCardPayload({ show_in_calendar: false }).show_in_calendar).toBe(false)
  })
})
