const SEVERITY_ORDER = { error: 0, warn: 1, info: 2 }
const STATUS_ORDER = { would_send: 0, already_sent: 1, channel_not_ready: 2, not_due: 3 }

export function severityLabel(severity) {
  if (severity === 'error') return '错误'
  if (severity === 'warn') return '警告'
  return '建议'
}

export function severityClass(severity) {
  if (severity === 'error') return 'bad'
  if (severity === 'warn') return 'warn'
  return 'info'
}

export function sortIssues(issues = []) {
  return [...issues].sort((a, b) => {
    const sa = SEVERITY_ORDER[a.severity] ?? 9
    const sb = SEVERITY_ORDER[b.severity] ?? 9
    if (sa !== sb) return sa - sb
    return String(a.code || '').localeCompare(String(b.code || ''))
  })
}

export function filterIssues(issues = [], filter = 'all') {
  if (filter === 'all') return sortIssues(issues)
  if (filter === 'reminder') return sortIssues(issues.filter((x) => ['user', 'notification'].includes(x.scope) || String(x.code || '').includes('remind')))
  return sortIssues(issues.filter((x) => x.severity === filter))
}

export function channelLabel(channel) {
  if (channel === 'telegram') return 'Telegram'
  if (channel === 'bark') return 'Bark'
  return '全部'
}

export function simulationStatusLabel(status) {
  const labels = {
    would_send: '将发送',
    already_sent: '重复跳过',
    channel_not_ready: '通道未就绪',
    not_due: '未到提醒日',
    invalid_reminder_days: '提醒配置异常',
    missing_next_renewal: '缺少续费日',
    inactive: '未启用',
    not_recurring: '非周期订阅'
  }
  return labels[status] || status || '未知'
}

export function simulationStatusClass(status) {
  if (status === 'would_send') return 'ok'
  if (status === 'already_sent') return 'info'
  if (['channel_not_ready', 'invalid_reminder_days', 'missing_next_renewal'].includes(status)) return 'warn'
  return 'muted'
}

export function sortSimulationItems(items = []) {
  return [...items].sort((a, b) => {
    const sa = STATUS_ORDER[a.status] ?? 9
    const sb = STATUS_ORDER[b.status] ?? 9
    if (sa !== sb) return sa - sb
    const da = a.next_renewal_date || ''
    const db = b.next_renewal_date || ''
    if (da !== db) return da.localeCompare(db)
    return String(a.subscription_name || '').localeCompare(String(b.subscription_name || ''))
  })
}

export function simulationSummary(items = []) {
  return items.reduce((out, item) => {
    out.total += 1
    if (item.status === 'would_send') out.would_send += 1
    else out.skipped += 1
    if (item.channel === 'telegram') out.telegram += 1
    if (item.channel === 'bark') out.bark += 1
    return out
  }, { total: 0, would_send: 0, skipped: 0, telegram: 0, bark: 0 })
}
