import { describe, expect, it } from 'vitest'

import { formatDateTimeInZone, formatTimeInZone } from './time'

describe('formatTimeInZone', () => {
  it('formats UTC strings in Asia/Shanghai by default', () => {
    expect(formatTimeInZone('2024-01-01T00:00:00Z')).toBe('08:00:00')
  })

  it('converts offset-aware strings to the requested timezone', () => {
    expect(formatTimeInZone('2024-01-01T08:00:00+08:00', 'UTC')).toBe('00:00:00')
  })

  it('returns empty string for invalid dates', () => {
    expect(formatTimeInZone('not-a-date')).toBe('')
    expect(formatTimeInZone(null)).toBe('')
  })

  it('falls back to Asia/Shanghai when timezone is invalid', () => {
    expect(formatTimeInZone('2024-01-01T00:00:00Z', 'Invalid/Timezone')).toBe('08:00:00')
  })

  it('treats date-only strings as local calendar dates without timezone shift', () => {
    expect(formatTimeInZone('2024-01-01', 'America/New_York')).toBe('00:00:00')
  })
})

describe('formatDateTimeInZone', () => {
  it('formats UTC strings with date in Asia/Shanghai by default', () => {
    expect(formatDateTimeInZone('2024-01-01T00:00:00Z')).toBe('2024-01-01 08:00:00')
  })

  it('converts UTC strings to the requested timezone', () => {
    expect(formatDateTimeInZone('2024-01-01T00:00:00Z', 'America/New_York')).toBe('2023-12-31 19:00:00')
  })

  it('returns empty string for invalid dates', () => {
    expect(formatDateTimeInZone('not-a-date')).toBe('')
    expect(formatDateTimeInZone(null)).toBe('')
  })

  it('falls back to Asia/Shanghai when timezone is invalid', () => {
    expect(formatDateTimeInZone('2024-01-01T00:00:00Z', 'Invalid/Timezone')).toBe('2024-01-01 08:00:00')
  })

  it('converts offset-aware strings to the requested timezone with date', () => {
    expect(formatDateTimeInZone('2024-01-01T08:00:00+08:00', 'UTC')).toBe('2024-01-01 00:00:00')
  })

  it('treats date-only strings as local calendar dates without timezone shift', () => {
    expect(formatDateTimeInZone('2024-01-01', 'America/New_York')).toBe('2024-01-01 00:00:00')
  })
})
