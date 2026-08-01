import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api'
import { addCycleDate, parseLocalDate, toISODate } from '../utils/date'

/**
 * 订阅操作编排：续费 / 删除 / 编辑三套弹窗的 state 与流程。
 *
 * 纯流程逻辑，不耦合任何页面的数据模型（不碰列表、排序、筛选、拖拽）。
 * 数据刷新、提示、新建捆绑包回调由调用方注入，保证 Dashboard 与订阅账本共用同一份实现。
 *
 * @param {object} opts
 * @param {() => Promise<void>} opts.reload 操作成功后调用的刷新函数（整页/列表刷新）。
 * @param {(msg: string, type?: string) => void} opts.toast 提示函数。
 * @param {(bundle: object) => void} [opts.onBundleCreated] 编辑表单新建捆绑包后回调。
 */
export function useSubscriptionActions({ reload, toast, onBundleCreated: handleBundleCreated } = {}) {
  const { t } = useI18n()

  // 续费确认弹窗
  const renewTarget = ref(null)
  const renewMode = ref('today')
  const renewing = ref(false)

  // 删除确认弹窗
  const delTarget = ref(null)
  const delPwd = ref('')
  const delErr = ref('')
  const deleting = ref(false)

  // 编辑 / 新建表单
  const showForm = ref(false)
  const formTarget = ref(null)

  function askRenew(s) {
    renewTarget.value = s
    renewMode.value = 'today'
  }
  function closeRenew() {
    renewTarget.value = null
  }
  const previewToday = computed(() =>
    renewTarget.value ? toISODate(addCycleDate(new Date(), renewTarget.value.cycle, renewTarget.value.cycle_count)) : ''
  )
  const previewDue = computed(() => {
    if (!renewTarget.value) return ''
    const base = renewTarget.value.next_renewal_date ? parseLocalDate(renewTarget.value.next_renewal_date) : new Date()
    return toISODate(addCycleDate(base, renewTarget.value.cycle, renewTarget.value.cycle_count))
  })
  async function confirmRenew() {
    if (!renewTarget.value || renewing.value) return
    // 请求期间用户可能关闭弹窗或改换目标，提前快照不可变字段。
    const target = renewTarget.value
    renewing.value = true
    try {
      const { data } = await api.post(`/api/subscriptions/${target.id}/renew`, { mode: renewMode.value })
      const kaKey = target.is_keepalive ? 'sub.keepalive.renewOk' : 'sub.renewOk'
      toast(t(kaKey, { date: data.next_renewal_date }))
      // 仅当用户未改换到其它目标时才关闭当前弹窗，避免误关后续打开的弹窗。
      if (renewTarget.value === target) closeRenew()
      await safeReload()
    } catch (e) {
      toast(e.response?.data?.detail || 'Error', 'err')
    } finally {
      renewing.value = false
    }
  }

  function askDelete(s) {
    delTarget.value = s
    delPwd.value = ''
    delErr.value = ''
  }
  function closeDelete() {
    delTarget.value = null
  }
  async function confirmDelete() {
    if (!delTarget.value || deleting.value || !delPwd.value) return
    const target = delTarget.value
    deleting.value = true
    delErr.value = ''
    try {
      await api.delete(`/api/subscriptions/${target.id}`, { data: { password: delPwd.value } })
      if (delTarget.value === target) closeDelete()
      toast(t('sub.delete'))
      await safeReload()
    } catch (e) {
      // 仅当用户仍停留在同一删除目标时才显示错误，避免污染后续打开的弹窗。
      if (delTarget.value === target) delErr.value = e.response?.data?.detail || 'Error'
    } finally {
      deleting.value = false
    }
  }

  function openEdit(s) {
    formTarget.value = s
    showForm.value = true
  }
  function closeForm() {
    showForm.value = false
    formTarget.value = null
  }
  function onFormSaved() {
    closeForm()
    toast(t('settings.saved'))
    safeReload()
  }

  // 写入已成功后的刷新单独建错误边界：刷新失败不应回滚成功语义。
  // 各页 reload 自身应对刷新失败降级（保留旧数据），这里仅兜底防未处理 rejection。
  async function safeReload() {
    try { await reload() } catch { /* reload 负责降级，此处静默 */ }
  }
  function onBundleCreated(bundle) {
    handleBundleCreated?.(bundle)
  }

  return {
    renewTarget, renewMode, renewing,
    delTarget, delPwd, delErr, deleting,
    showForm, formTarget,
    askRenew, closeRenew, confirmRenew, previewToday, previewDue,
    askDelete, closeDelete, confirmDelete,
    openEdit, closeForm, onFormSaved, onBundleCreated
  }
}
