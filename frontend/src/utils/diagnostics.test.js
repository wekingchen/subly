import { describe, expect, it } from 'vitest'

import {
  channelLabel,
  filterIssues,
  severityClass,
  severityLabel,
  simulationStatusClass,
  simulationStatusLabel,
  simulationSummary,
  sortIssues,
  sortSimulationItems
} from './diagnostics'

describe('diagnostics issue helpers', () => {
  const issues = [
    { severity: 'info', scope: 'system', code: 'z' },
    { severity: 'error', scope: 'subscription', code: 'b' },
    { severity: 'warn', scope: 'notification', code: 'remind_x' },
    { severity: 'error', scope: 'user', code: 'a' }
  ]

  it('sorts issues by severity then code', () => {
    expect(sortIssues(issues).map((x) => x.code)).toEqual(['a', 'b', 'remind_x', 'z'])
  })

  it('filters issues by severity and reminder scope', () => {
    expect(filterIssues(issues, 'error').map((x) => x.code)).toEqual(['a', 'b'])
    expect(filterIssues(issues, 'reminder').map((x) => x.code)).toEqual(['a', 'remind_x'])
  })

  it('labels severity classes', () => {
    expect(severityLabel('error')).toBe('错误')
    expect(severityLabel('warn')).toBe('警告')
    expect(severityLabel('info')).toBe('建议')
    expect(severityClass('error')).toBe('bad')
    expect(severityClass('warn')).toBe('warn')
    expect(severityClass('info')).toBe('info')
  })
})

describe('reminder simulation helpers', () => {
  const items = [
    { status: 'not_due', channel: 'bark', next_renewal_date: '2026-08-01', subscription_name: 'B' },
    { status: 'would_send', channel: 'telegram', next_renewal_date: '2026-07-01', subscription_name: 'A' },
    { status: 'already_sent', channel: 'bark', next_renewal_date: '2026-07-02', subscription_name: 'C' }
  ]

  it('labels channels and statuses', () => {
    expect(channelLabel('telegram')).toBe('Telegram')
    expect(channelLabel('bark')).toBe('Bark')
    expect(channelLabel('all')).toBe('全部')
    expect(simulationStatusLabel('would_send')).toBe('将发送')
    expect(simulationStatusLabel('channel_not_ready')).toBe('通道未就绪')
    expect(simulationStatusClass('would_send')).toBe('ok')
    expect(simulationStatusClass('channel_not_ready')).toBe('warn')
  })

  it('sorts simulation items by actionable status first', () => {
    expect(sortSimulationItems(items).map((x) => x.status)).toEqual(['would_send', 'already_sent', 'not_due'])
  })

  it('builds summary from returned items', () => {
    expect(simulationSummary(items)).toEqual({ total: 3, would_send: 1, skipped: 2, telegram: 1, bark: 2 })
  })
})
