import { addCycleDate, parseLocalDate, toISODate } from './date'

export function createBlankSubscriptionForm({ now = new Date() } = {}) {
  return {
    id: null, name: '', plan: '', icon: '', amount: 0, currency: 'CNY',
    category_id: null, payment_method_id: null, bundle_id: null, billing_type: 'recurring',
    is_keepalive: false,
    cycle: 'month', cycle_count: 1, start_date: toISODate(now),
    next_renewal_date: '', end_date: null, url: '', notes: '', remark: '', ipv4: '', ipv6: '',
    remind_days_before: '7,1', auto_renew: true, is_active: true,
    show_in_calendar: true, family_members: []
  }
}

export function computeNextRenewalDate(form, currentValue = form?.next_renewal_date || '', options = {}) {
  if (form?.billing_type !== 'recurring') return ''
  if (!form.start_date) return currentValue
  const start = parseLocalDate(form.start_date)
  if (!start) return currentValue
  const today = parseLocalDate(toISODate(options.today ?? options.now ?? new Date()))
  let next = addCycleDate(start, form.cycle, form.cycle_count)
  while (next < today) {
    const previous = next
    next = addCycleDate(next, form.cycle, form.cycle_count)
    if (next <= previous) break
  }
  return toISODate(next)
}

export function cloneSubscriptionForEdit(subscription = {}) {
  return {
    ...subscription,
    next_renewal_date: subscription.next_renewal_date || '',
    family_members: [...(subscription.family_members || [])]
  }
}

export function buildSubscriptionPayload(form) {
  const payload = { ...form }
  if (!payload.next_renewal_date) delete payload.next_renewal_date
  return payload
}
