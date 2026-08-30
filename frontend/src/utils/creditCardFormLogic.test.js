import { describe, expect, it } from 'vitest'
import { parseLastFours, remainingLastFoursText } from './creditCardFormLogic'

// 这两个纯函数是"部分失败后重试只建剩余的卡"防重复链路的事实源：
// FormModal 的 watch（收缩输入框）与 submit（重新解析）都调用它们，
// 改坏任一侧都会让这里的断言失败。
describe('remainingLastFoursText', () => {
  const batchError = {
    message: '已创建 1 张，第 2 张失败',
    remainingLastFours: ['2234', '3234']
  }

  it('把结构化错误的剩余尾号拼成输入框文本', () => {
    expect(remainingLastFoursText(batchError)).toBe('2234, 3234')
  })

  it('纯文本错误、无剩余项或空数组时不收缩（返回 null 保持用户输入）', () => {
    expect(remainingLastFoursText('普通错误文本')).toBeNull()
    expect(remainingLastFoursText({ message: 'x', remainingLastFours: [] })).toBeNull()
    expect(remainingLastFoursText(null)).toBeNull()
    expect(remainingLastFoursText(undefined)).toBeNull()
  })
})

describe('parseLastFours', () => {
  it('支持中英文逗号与空白分隔', () => {
    expect(parseLastFours('1234,2234')).toEqual(['1234', '2234'])
    expect(parseLastFours('1234， 2234 3234')).toEqual(['1234', '2234', '3234'])
  })

  it('收缩后的文本重新解析只含剩余尾号——重试不重复建已成功的卡', () => {
    // 模拟完整链路：1234 成功、2234 失败 → 收缩文本 → 用户直接再保存。
    const contracted = remainingLastFoursText({
      message: '',
      remainingLastFours: ['2234', '3234']
    })
    expect(parseLastFours(contracted)).toEqual(['2234', '3234'])
    expect(parseLastFours(contracted)).not.toContain('1234')
  })

  it('空输入解析为空数组（空尾号=单卡契约）', () => {
    expect(parseLastFours('')).toEqual([])
    expect(parseLastFours(null)).toEqual([])
  })
})
