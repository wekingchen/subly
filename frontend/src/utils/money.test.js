import { describe, expect, it } from 'vitest'

import { amountOf, formatMoney, hasBaseEquivalent } from './money'

describe('amountOf', () => {
  it('prefers amount_in_base over amount', () => {
    expect(amountOf({ amount_in_base: 88, amount: 99 })).toBe(88)
  })

  it('falls back to amount when amount_in_base is missing', () => {
    expect(amountOf({ amount: '12.5' })).toBe(12.5)
  })

  it('uses fallback when item is missing', () => {
    expect(amountOf(null, 7)).toBe(7)
  })

  it('uses fallback when value is not finite', () => {
    expect(amountOf({ amount_in_base: 'not-a-number', amount: 12 }, 3)).toBe(3)
  })

  it('returns zero when both value and fallback are invalid', () => {
    expect(amountOf({ amount: 'bad' }, 'also-bad')).toBe(0)
  })
})


describe('hasBaseEquivalent', () => {
  it('returns true only for different currencies with a finite base amount', () => {
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: 143.2 }, 'CNY')).toBe(true)
  })

  it('returns false when the subscription currency already matches the base currency', () => {
    expect(hasBaseEquivalent({ currency: 'CNY', amount_in_base: 143.2 }, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: 143.2 }, 'usd')).toBe(false)
  })

  it('returns false when amount_in_base is not finite', () => {
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: 'bad' }, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: undefined }, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: null }, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: '' }, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: '   ' }, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: false }, 'CNY')).toBe(false)
  })

  it('returns false when item or base currency is missing or invalid', () => {
    expect(hasBaseEquivalent(null, 'CNY')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: 143.2 }, '')).toBe(false)
    expect(hasBaseEquivalent({ currency: 'USD', amount_in_base: 143.2 }, true)).toBe(false)
    expect(hasBaseEquivalent({ currency: true, amount_in_base: 143.2 }, 'CNY')).toBe(false)
  })
})

describe('formatMoney', () => {
  it('formats with currency prefix by default', () => {
    expect(formatMoney(12.3, 'CNY')).toBe('CNY 12.30')
  })


  it('formats with currency suffix', () => {
    expect(formatMoney(12.3, 'USD', { position: 'suffix' })).toBe('12.30 USD')
  })

  it('can omit spaces around the currency', () => {
    expect(formatMoney(12.3, 'USD', { space: false })).toBe('USD12.30')
    expect(formatMoney(12.3, 'USD', { position: 'suffix', space: false })).toBe('12.30USD')
  })

  it('can omit the currency label', () => {
    expect(formatMoney(12.3, 'USD', { position: 'none' })).toBe('12.30')
    expect(formatMoney(12.3, '', {})).toBe('12.30')
  })

  it('supports custom decimals', () => {
    expect(formatMoney(12.6, 'CNY', { decimals: 0 })).toBe('CNY 13')
  })

  it('formats invalid amounts as zero', () => {
    expect(formatMoney('bad', 'CNY')).toBe('CNY 0.00')
  })
})
