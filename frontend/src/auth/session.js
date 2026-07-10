let accessToken = null

function resolveStorage(storage) {
  if (storage !== undefined) return storage
  return typeof localStorage === 'undefined' ? null : localStorage
}

function responseStatus(error) {
  return error?.response?.status
}

export function getAccessToken() {
  return accessToken
}

export function setAccessToken(token) {
  accessToken = token || null
}

export function clearAccessToken() {
  accessToken = null
}

export function getLegacyRefreshToken(storage) {
  return resolveStorage(storage)?.getItem('refresh_token') || null
}

export function removeLegacyAccessToken(storage) {
  resolveStorage(storage)?.removeItem('access_token')
}

export function removeLegacyTokens(storage) {
  const target = resolveStorage(storage)
  target?.removeItem('access_token')
  target?.removeItem('refresh_token')
}

export function clearBrowserSession(storage) {
  clearAccessToken()
  removeLegacyTokens(storage)
}

export async function bootstrapSession(refreshTokens, storage) {
  removeLegacyAccessToken(storage)
  try {
    const data = await refreshTokens()
    setAccessToken(data?.access_token)
    removeLegacyTokens(storage)
    return data
  } catch (error) {
    const status = responseStatus(error)
    if (status === 403) {
      clearBrowserSession(storage)
      return null
    }
    if (status !== 401) throw error
  }

  const legacyRefreshToken = getLegacyRefreshToken(storage)
  if (!legacyRefreshToken) {
    clearBrowserSession(storage)
    return null
  }

  try {
    const data = await refreshTokens(legacyRefreshToken)
    setAccessToken(data?.access_token)
    removeLegacyTokens(storage)
    return data
  } catch (error) {
    const status = responseStatus(error)
    if (status === 401 || status === 403) {
      clearBrowserSession(storage)
      return null
    }
    throw error
  }
}
