import { describe, expect, it } from 'vitest'

import { formatTimeInZone } from './time'

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
})
