import { describe, expect, it } from 'vitest'

import {
  channelLabel,
  filterIssues,
  isFixable,
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
    { severity: 'info', scope: 'system', code: 'currency_missing' },
    { severity: 'error', scope: 'subscription', code: 'negative_amount' },
    { severity: 'warn', scope: 'notification', code: 'telegram_config_incomplete' },
    { severity: 'warn', scope: 'subscription', code: 'invalid_remind_days' },
    { severity: 'info', scope: 'user', code: 'disabled_user_has_active_subscriptions' }
  ]

  it('sorts issues by severity then code', () => {
    expect(sortIssues(issues).map((x) => x.code)).toEqual([
      'negative_amount',
      'invalid_remind_days',
      'telegram_config_incomplete',
      'currency_missing',
      'disabled_user_has_active_subscriptions'
    ])
  })

  it('filters issues by severity and explicit reminder codes', () => {
    expect(filterIssues(issues, 'error').map((x) => x.code)).toEqual(['negative_amount'])
    // 提醒筛选只纳入显式列出的提醒类 code，不受 scope 误导：
    // telegram_config_incomplete / invalid_remind_days 属于提醒相关；
    // disabled_user_has_active_subscriptions（scope=user）不再被误纳入。
    expect(filterIssues(issues, 'reminder').map((x) => x.code)).toEqual([
      'invalid_remind_days',
      'telegram_config_incomplete'
    ])
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

describe('isFixable', () => {
  it('returns true for repairable codes with subscription_id', () => {
    expect(isFixable({ code: 'category_not_owned', subscription_id: 1 })).toBe(true)
    expect(isFixable({ code: 'invalid_remind_days', subscription_id: 2 })).toBe(true)
  })

  it('returns false for non-repairable (B class) codes', () => {
    expect(isFixable({ code: 'invalid_billing_type', subscription_id: 1 })).toBe(false)
    expect(isFixable({ code: 'telegram_config_incomplete', subscription_id: 1 })).toBe(false)
  })

  it('returns false without subscription_id (cannot locate target)', () => {
    expect(isFixable({ code: 'category_not_owned' })).toBe(false)
    expect(isFixable({})).toBe(false)
  })
})
