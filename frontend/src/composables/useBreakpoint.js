import { onBeforeUnmount, onMounted, ref } from 'vue'

// 响应式媒体查询：返回是否匹配 query 的 ref，自动在挂载时监听、卸载时清理。
// 与 SubscriptionActionMenuLayer 内的 matchMedia 模式一致（TODO: 后续可让该层改用本 composable）。
export function useBreakpoint(query) {
  // 纯客户端 SPA，首帧即可读真实匹配，避免 onMounted 前先渲染错版本再闪烁
  const matches = ref(typeof window !== 'undefined' && window.matchMedia(query).matches)
  let mq = null

  function sync() { if (mq) matches.value = mq.matches }

  onMounted(() => {
    mq = window.matchMedia(query)
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
