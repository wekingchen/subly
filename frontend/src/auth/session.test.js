import { afterEach, describe, expect, it } from 'vitest'
import {
  bootstrapSession,
  clearAccessToken,
  getAccessToken,
  setAccessToken
} from './session'

function makeStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    snapshot: () => Object.fromEntries(values)
  }
}

function httpError(status) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } })
}

afterEach(() => clearAccessToken())

describe('browser auth session', () => {
  it('keeps access token in memory only', () => {
    setAccessToken('access')
    expect(getAccessToken()).toBe('access')
    clearAccessToken()
    expect(getAccessToken()).toBe(null)
  })

  it('prefers cookie refresh and deletes all legacy tokens on success', async () => {
    const storage = makeStorage({ access_token: 'old-access', refresh_token: 'old-refresh' })
    const calls = []
    const result = await bootstrapSession(async (legacy) => {
      calls.push(legacy)
      return { access_token: 'new-access' }
    }, storage)

    expect(result.access_token).toBe('new-access')
    expect(calls).toEqual([undefined])
    expect(getAccessToken()).toBe('new-access')
    expect(storage.snapshot()).toEqual({})
  })

  it('uses a legacy refresh token once after cookie refresh returns 401', async () => {
    const storage = makeStorage({ access_token: 'old-access', refresh_token: 'legacy-refresh' })
    const calls = []
    const result = await bootstrapSession(async (legacy) => {
      calls.push(legacy)
      if (!legacy) throw httpError(401)
      return { access_token: 'migrated-access' }
    }, storage)

    expect(result.access_token).toBe('migrated-access')
    expect(calls).toEqual([undefined, 'legacy-refresh'])
    expect(storage.snapshot()).toEqual({})
  })

  it('clears legacy tokens when refresh credentials are explicitly rejected', async () => {
    const storage = makeStorage({ access_token: 'old-access', refresh_token: 'legacy-refresh' })
    const result = await bootstrapSession(async () => {
      throw httpError(403)
    }, storage)

    expect(result).toBe(null)
    expect(getAccessToken()).toBe(null)
    expect(storage.snapshot()).toEqual({})
  })

  it('preserves the legacy refresh token on transient cookie failure', async () => {
    const storage = makeStorage({ access_token: 'old-access', refresh_token: 'legacy-refresh' })
    await expect(bootstrapSession(async () => {
      throw new Error('network down')
    }, storage)).rejects.toThrow('network down')

    expect(storage.snapshot()).toEqual({ refresh_token: 'legacy-refresh' })
    expect(getAccessToken()).toBe(null)
  })

  it('preserves the legacy refresh token on transient migration failure', async () => {
    const storage = makeStorage({ access_token: 'old-access', refresh_token: 'legacy-refresh' })
    await expect(bootstrapSession(async (legacy) => {
      if (!legacy) throw httpError(401)
      throw new Error('gateway timeout')
    }, storage)).rejects.toThrow('gateway timeout')

    expect(storage.snapshot()).toEqual({ refresh_token: 'legacy-refresh' })
    expect(getAccessToken()).toBe(null)
  })
})
