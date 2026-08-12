import { describe, expect, it } from 'vitest'
import { createRequestGuard, useDataRequest } from './dataRequest'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('createRequestGuard', () => {
  it('只允许最后开始的请求写入结果', () => {
    const guard = createRequestGuard()
    const first = guard.begin()
    const second = guard.begin()

    expect(guard.isCurrent(first)).toBe(false)
    expect(guard.isCurrent(second)).toBe(true)
  })
})

describe('useDataRequest', () => {
  it('区分首次空数据、刷新中与刷新失败后的陈旧数据', async () => {
    const request = useDataRequest({ initialData: [] })

    const firstRun = request.run(async () => [])
    expect(request.state()).toBe('loading')
    await firstRun
    expect(request.state()).toBe('empty')

    request.data.value = [{ id: 1 }]
    const refresh = deferred()
    const refreshRun = request.run(() => refresh.promise)
    expect(request.state()).toBe('refreshing')
    refresh.reject(new Error('offline'))
    await refreshRun

    expect(request.data.value).toEqual([{ id: 1 }])
    expect(request.state()).toBe('stale')
  })

  it('首次失败是阻断错误，成功重试后恢复', async () => {
    const request = useDataRequest({ initialData: [] })

    await request.run(async () => { throw new Error('boom') })
    expect(request.state()).toBe('error')

    await request.run(async () => [{ id: 2 }])
    expect(request.state()).toBe('ready')
    expect(request.data.value).toEqual([{ id: 2 }])
  })

  it('忽略晚到的旧请求结果', async () => {
    const request = useDataRequest({ initialData: [] })
    const slow = deferred()
    const fast = deferred()

    const slowRun = request.run(() => slow.promise)
    const fastRun = request.run(() => fast.promise)
    fast.resolve([{ id: 'new' }])
    await fastRun
    slow.resolve([{ id: 'old' }])
    await slowRun

    expect(request.data.value).toEqual([{ id: 'new' }])
  })
})
