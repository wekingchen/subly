import { describe, expect, it, vi } from 'vitest'
import { useConfirm } from './useConfirm'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('useConfirm', () => {
  it('prevents repeated confirmation while the action is pending', async () => {
    const action = deferred()
    const onConfirm = vi.fn(() => action.promise)
    const confirm = useConfirm()
    confirm.open({ title: '删除', onConfirm })

    const first = confirm.confirm()
    const second = confirm.confirm()

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(confirm.state.value.pending).toBe(true)
    confirm.close()
    expect(confirm.state.value?.open).toBe(true)

    action.resolve()
    await Promise.all([first, second])
    expect(confirm.state.value).toBe(null)
  })

  it('keeps the dialog open and exposes the rejection message', async () => {
    const confirm = useConfirm()
    confirm.open({
      title: '删除',
      onConfirm: async () => {
        throw Object.assign(new Error('fallback'), { response: { data: { detail: '删除失败' } } })
      }
    })

    await confirm.confirm()

    expect(confirm.state.value.open).toBe(true)
    expect(confirm.state.value.pending).toBe(false)
    expect(confirm.state.value.error).toBe('删除失败')
  })

  it('does not let an older action clear a newer confirmation', async () => {
    const action = deferred()
    const confirm = useConfirm()
    confirm.open({ title: '旧操作', onConfirm: () => action.promise })
    const pending = confirm.confirm()

    confirm.open({ title: '新操作', onConfirm: async () => {} })
    action.resolve()
    await pending

    expect(confirm.state.value.title).toBe('新操作')
    expect(confirm.state.value.pending).toBe(false)
  })
})
