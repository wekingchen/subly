// 信用卡表单的尾号解析与"部分失败后收缩"逻辑。
// 独立成纯函数模块，让表单 watch/submit 与测试共用同一份实现，
// 避免收缩逻辑被改坏时（重试重复建卡）纯单测仍全绿。

// 从输入文本解析尾号数组：逗号/中文逗号/空白分隔。
export function parseLastFours(text) {
  return String(text ?? '')
    .split(/[,，\s]+/)
    .filter(Boolean)
    .map((value) => value.trim())
}

// 部分失败后的剩余尾号拼回输入框文本；已成功项被剔除，
// 用户直接重试只提交剩余部分，不会重复创建已成功的卡。
export function remainingLastFoursText(error) {
  const remaining = error && typeof error === 'object' ? error.remainingLastFours : null
  if (!Array.isArray(remaining) || !remaining.length) return null
  return remaining.join(', ')
}
