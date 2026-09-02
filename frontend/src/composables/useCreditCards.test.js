import { describe, expect, it, vi, beforeEach } from 'vitest'

// save() 的批量行为测试：mock ../api 模块，验证真实循环逻辑而非仅 payload 形状。
vi.mock('../api', () => ({ default: { post: vi.fn(), put: vi.fn(), delete: vi.fn(), get: vi.fn() } }))

import api from '../api'
import { buildCreditCardPayload, useCreditCards } from './useCreditCards'

const SOURCE = {
  display_name: '主卡',
  bank_name: '招商银行',
  statement_day: 5,
  due_day: 25,
  remind_days_before: [7, 1],
  credit_limit: null,
  is_active: true,
  show_in_calendar: true
}

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
      credit_limit: 50000,
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
      credit_limit: 50000,
      fee_waiver_anchor_date: null,
      fee_waiver_target_count: null,
      fee_waiver_target_amount: null,
      is_active: false,
      show_in_calendar: true
    })
  })

  it('normalizes fee waiver fields: empty to null, values passed through', () => {
    expect(buildCreditCardPayload({ fee_waiver_anchor_date: '', fee_waiver_target_count: '', fee_waiver_target_amount: '' }))
      .toMatchObject({ fee_waiver_anchor_date: null, fee_waiver_target_count: null, fee_waiver_target_amount: null })
    expect(buildCreditCardPayload({ fee_waiver_anchor_date: '2025-03-15T00:00:00', fee_waiver_target_count: 6, fee_waiver_target_amount: 30000 }))
      .toMatchObject({ fee_waiver_anchor_date: '2025-03-15', fee_waiver_target_count: 6, fee_waiver_target_amount: 30000 })
  })

  it('parses a comma-separated reminder text into an integer array', () => {
    const payload = buildCreditCardPayload({ remind_days_before: '7, 3, 1, 0' })
    expect(payload.remind_days_before).toEqual([7, 3, 1, 0])
  })

  it('always sends remind_days_before as an array, never a scalar', () => {
    expect(Array.isArray(buildCreditCardPayload({}).remind_days_before)).toBe(true)
    expect(Array.isArray(buildCreditCardPayload({ remind_days_before: '' }).remind_days_before)).toBe(true)
  })

  it('passes credit_limit through and normalizes empty input to null', () => {
    expect(buildCreditCardPayload({ credit_limit: 50000 }).credit_limit).toBe(50000)
    expect(buildCreditCardPayload({ credit_limit: '' }).credit_limit).toBeNull()
    expect(buildCreditCardPayload({}).credit_limit).toBeNull()
  })

  it('allows an empty last_four so the backend stores it as null', () => {
    expect(buildCreditCardPayload({ last_four: '' }).last_four).toBe('')
    expect(buildCreditCardPayload({}).last_four).toBe('')
  })

  it('defaults switches to enabled but preserves explicit false', () => {
    expect(buildCreditCardPayload({}).is_active).toBe(true)
    expect(buildCreditCardPayload({ show_in_calendar: false }).show_in_calendar).toBe(false)
  })
})

describe('useCreditCards save batch behavior', () => {
  beforeEach(() => {
    // mockReset 清掉 calls 与 once 队列（clearAllMocks 不会清 once 队列，
    // 会让上一个测试的 mockRejectedValueOnce 泄漏到下一个测试）。
    api.post.mockReset()
    api.put.mockReset()
    api.delete.mockReset()
    api.get.mockReset()
  })

  function makeStore() {
    return useCreditCards()
  }

  it('creates one card per last four and appends the last four to the name', async () => {
    api.post.mockImplementation((_url, payload) =>
      Promise.resolve({ data: { id: payload.last_four === '1234' ? 1 : 2, ...payload } })
    )
    const store = makeStore()

    const result = await saveBatch(store, { ...SOURCE, last_fours: ['1234', '2234'] })

    expect(api.post).toHaveBeenCalledTimes(2)
    expect(api.post.mock.calls[0][1].display_name).toBe('主卡 1234')
    expect(api.post.mock.calls[1][1].display_name).toBe('主卡 2234')
    expect(result.created).toBe(2)
    expect(result.total).toBe(2)
    expect(store.cards.value.map((card) => card.id)).toEqual([2, 1])
  })

  it('does not duplicate the last four when the name already contains it', async () => {
    api.post.mockResolvedValue({ data: { id: 1 } })
    const store = makeStore()

    await saveBatch(store, { ...SOURCE, display_name: '主卡 1234', last_fours: ['1234'] })

    expect(api.post.mock.calls[0][1].display_name).toBe('主卡 1234')
  })

  it('counts an empty last four as a single card', async () => {
    api.post.mockResolvedValue({ data: { id: 7, display_name: '无尾号卡' } })
    const store = makeStore()

    const result = await saveBatch(store, { ...SOURCE, display_name: '无尾号卡', last_fours: [] })

    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post.mock.calls[0][1].last_four).toBe('')
    expect(result.created).toBe(1)
    expect(result.total).toBe(1)
  })

  it('exposes structured batch info and remaining last fours when a middle card fails', async () => {
    api.post
      .mockResolvedValueOnce({ data: { id: 1 } })
      .mockRejectedValueOnce({ response: { data: { detail: '银行名称过长' } } })
      .mockResolvedValueOnce({ data: { id: 3 } })
    const store = makeStore()

    const error = await saveBatch(store, { ...SOURCE, last_fours: ['1234', '2234', '3234'] }).catch((e) => e)

    expect(api.post).toHaveBeenCalledTimes(2)
    expect(error.batch.created).toBe(1)
    expect(error.batch.total).toBe(3)
    expect(error.batch.failedIndex).toBe(1)
    expect(error.batch.remainingLastFours).toEqual(['2234', '3234'])
    // 已成功的卡保留在本地列表，不回滚。
    expect(store.cards.value).toHaveLength(1)
  })

  it('retries only the remaining last fours after a partial failure', async () => {
    api.post
      .mockResolvedValueOnce({ data: { id: 1 } })
      .mockRejectedValueOnce({ response: { data: { detail: '临时失败' } } })
    const store = makeStore()
    const firstError = await saveBatch(store, { ...SOURCE, last_fours: ['1234', '2234'] }).catch((e) => e)
    expect(firstError.batch.remainingLastFours).toEqual(['2234'])
    vi.clearAllMocks()
    api.post.mockResolvedValue({ data: { id: 9 } })

    // 表单收缩后只带剩余尾号重试：不会重复创建 1234。
    await saveBatch(store, { ...SOURCE, last_fours: ['2234'] })

    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post.mock.calls[0][1].last_four).toBe('2234')
    expect(api.post.mock.calls[0][1].display_name).toBe('主卡 2234')
  })

  it('edits an existing card through PUT without creating duplicates', async () => {
    api.put.mockResolvedValue({ data: { id: 5, display_name: '改后名' } })
    const store = makeStore()
    store.cards.value = [{ id: 5, display_name: '原名' }]

    const result = await store.save({ id: 5 }, { ...SOURCE, display_name: '改后名' })

    expect(api.put).toHaveBeenCalledTimes(1)
    expect(api.post).not.toHaveBeenCalled()
    expect(result.created).toBe(1)
    expect(store.cards.value[0].display_name).toBe('改后名')
  })

  it('returns null without calling the api when a mutation is already pending', async () => {
    let release
    api.post.mockImplementation(() => new Promise((resolve) => { release = resolve }))
    const store = makeStore()
    const first = store.save(null, { ...SOURCE, last_fours: ['1234'] })
    const second = await store.save(null, { ...SOURCE, last_fours: ['2234'] })

    expect(second).toBeNull()
    release({ data: { id: 1 } })
    await first
  })
})

async function saveBatch(store, source) {
  return store.save(null, source)
}
