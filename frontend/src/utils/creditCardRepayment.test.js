import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { formatAmountInput, nextAmountOnFocus, parseRepayAmount, statementRemainingAmount } from './creditCardRepayment'

describe('parseRepayAmount', () => {
  it('接受正数与最多两位小数', () => {
    expect(parseRepayAmount('600', 600)).toEqual({ ok: true, value: 600 })
    expect(parseRepayAmount('600.5', 600.5)).toEqual({ ok: true, value: 600.5 })
    expect(parseRepayAmount('0.01', 1)).toEqual({ ok: true, value: 0.01 })
    expect(parseRepayAmount(' 600 ', 600)).toEqual({ ok: true, value: 600 }) // 首尾空白容忍
  })

  it('拒绝空串、非法格式、非正数', () => {
    expect(parseRepayAmount('', 600).error).toBe('invalid')
    expect(parseRepayAmount('abc', 600).error).toBe('invalid')
    expect(parseRepayAmount('600.123', 600).error).toBe('invalid') // 三位小数
    expect(parseRepayAmount('1,000', 1000).error).toBe('invalid') // 千分位逗号
    expect(parseRepayAmount('-5', 600).error).toBe('invalid')
    expect(parseRepayAmount('1e3', 600).error).toBe('invalid')
    expect(parseRepayAmount('0', 600).error).toBe('invalid')
  })

  it('超过剩余待还按分比较拒绝（0.1+0.7 不小于 0.8）', () => {
    expect(parseRepayAmount('600.01', 600).error).toBe('exceeds')
    // 分边界：剩余 0.8，输入 0.8 合法（0.7+0.1=0.7999… 场景）
    expect(parseRepayAmount('0.8', 0.8)).toEqual({ ok: true, value: 0.8 })
    expect(parseRepayAmount('0.81', 0.8).error).toBe('exceeds')
  })
})

describe('nextAmountOnFocus', () => {
  it('值等于未改动默认值时清空（placeholder 兜底）', () => {
    expect(nextAmountOnFocus('600', '600')).toBe('')
  })

  it('用户已改值时全选保留（不销毁输入）', () => {
    const select = vi.fn()
    const result = nextAmountOnFocus('350', '600', select)
    expect(result).toBe('350')
    expect(select).toHaveBeenCalledTimes(1)
  })
})

describe('formatAmountInput', () => {
  it('整数不带小数、非整数两位、无千分位', () => {
    expect(formatAmountInput(600)).toBe('600')
    expect(formatAmountInput(600.5)).toBe('600.50')
    expect(formatAmountInput(8127.68)).toBe('8127.68')
  })
})

describe('statementRemainingAmount', () => {
  it('按分计算剩余，金额未知返回 null，无已还按 0 计', () => {
    expect(statementRemainingAmount(1000, 400)).toBe(600)
    expect(statementRemainingAmount(0.8, 0.1)).toBe(0.7)   // 0.8-0.1 浮点陷阱场景
    expect(statementRemainingAmount(500, null)).toBe(500)
    expect(statementRemainingAmount(null, 400)).toBeNull()
  })
})

// 审核 Medium 2 回归（静态断言）：RepaymentModal 不得配置 initial-focus 指向
// 金额输入框——AppModal 的自动聚焦会立即触发 focus 清空，把「默认填剩余全额、
// 一次还清直接确认」的主路径破坏掉（输入框变空 → 点确认报「请输入有效金额」）。
// 项目的组件测试基建只有纯函数（无 @vue/test-utils），用源码静态断言锁住。
const MODAL_SOURCE = readFileSync(
  fileURLToPath(new URL('../components/credit-cards/RepaymentModal.vue', import.meta.url)),
  'utf-8'
)

describe('RepaymentModal 无自动聚焦清空（审核 Medium 2）', () => {
  it('弹窗不配置 initial-focus（避免自动聚焦触发清空默认全额）', () => {
    expect(MODAL_SOURCE).not.toContain('initial-focus')
    // focus 清空逻辑仍在（用户主动点入时清空是需求）
    expect(MODAL_SOURCE).toContain('@focus="onFocus"')
  })

  it('打开时默认值来自剩余待还（formatAmountInput 裸数字）', () => {
    expect(MODAL_SOURCE).toContain('formatAmountInput(props.target.remaining)')
  })
})

describe('CreditCardStatementList 分派含 verify 门卫（六审 Low 1）', () => {
  it('mismatch 账单不走还款弹窗（走 PATCH 快捷标记）', () => {
    const source = readFileSync(
      fileURLToPath(new URL('../components/credit-cards/CreditCardStatementList.vue', import.meta.url)),
      'utf-8'
    )
    expect(source).toContain("s.verify_status === 'ok' && s.total_due != null && remainingOf(s) > 0")
  })
})
