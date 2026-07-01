const FALLBACK_TZ = 'Asia/Shanghai'

function partsToTime(parts) {
  const values = {}
  for (const part of parts) {
    if (part.type !== 'literal') values[part.type] = part.value
  }
  return `${values.hour || '00'}:${values.minute || '00'}:${values.second || '00'}`
}

export function formatTimeInZone(value, timezone = FALLBACK_TZ) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const options = {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: timezone || FALLBACK_TZ
  }
  try {
    return partsToTime(new Intl.DateTimeFormat('zh-CN', options).formatToParts(date))
  } catch {
    return partsToTime(new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: FALLBACK_TZ }).formatToParts(date))
  }
}
