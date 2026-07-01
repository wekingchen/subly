const FALLBACK_TZ = 'Asia/Shanghai'
const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})$/

function partsToValues(parts) {
  const values = {}
  for (const part of parts) {
    if (part.type !== 'literal') values[part.type] = part.value
  }
  return values
}

function partsToTime(parts) {
  const values = partsToValues(parts)
  return `${values.hour || '00'}:${values.minute || '00'}:${values.second || '00'}`
}

function partsToDateTime(parts) {
  const values = partsToValues(parts)
  return `${values.year || '0000'}-${values.month || '00'}-${values.day || '00'} ${values.hour || '00'}:${values.minute || '00'}:${values.second || '00'}`
}

function dateOnlyParts(value) {
  const m = typeof value === 'string' && value.match(DATE_ONLY_RE)
  if (!m) return null
  return [
    { type: 'year', value: m[1] },
    { type: 'month', value: m[2] },
    { type: 'day', value: m[3] },
    { type: 'hour', value: '00' },
    { type: 'minute', value: '00' },
    { type: 'second', value: '00' }
  ]
}

function formatParts(value, timezone, options) {
  if (!value) return null
  const localParts = dateOnlyParts(value)
  if (localParts) return localParts
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const opts = { ...options, timeZone: timezone || FALLBACK_TZ }
  try {
    return new Intl.DateTimeFormat('zh-CN', opts).formatToParts(date)
  } catch {
    return new Intl.DateTimeFormat('zh-CN', { ...opts, timeZone: FALLBACK_TZ }).formatToParts(date)
  }
}

export function formatTimeInZone(value, timezone = FALLBACK_TZ) {
  const parts = formatParts(value, timezone, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
  return parts ? partsToTime(parts) : ''
}

export function formatDateTimeInZone(value, timezone = FALLBACK_TZ) {
  const parts = formatParts(value, timezone, {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
  return parts ? partsToDateTime(parts) : ''
}
