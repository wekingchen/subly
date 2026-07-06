import { onBeforeUnmount, onMounted, ref } from 'vue'

// 响应式媒体查询：返回是否匹配 query 的 ref，自动在挂载时监听、卸载时清理。
// 与 SubscriptionActionMenuLayer 内的 matchMedia 模式一致。
export function useBreakpoint(query) {
  // setup 阶段即构造 MQL 并取初值，避免 onMounted 前先渲染错版本再闪烁；监听在 onMounted 注册
  const mq = typeof window !== 'undefined' ? window.matchMedia(query) : null
  const matches = ref(mq ? mq.matches : false)

  function sync() { if (mq) matches.value = mq.matches }

  onMounted(() => {
    if (!mq) return
    sync()
    if (mq.addEventListener) mq.addEventListener('change', sync)
    else mq.addListener?.(sync)
  })

  onBeforeUnmount(() => {
    if (!mq) return
    if (mq.removeEventListener) mq.removeEventListener('change', sync)
    else mq.removeListener?.(sync)
  })

  return matches
}
