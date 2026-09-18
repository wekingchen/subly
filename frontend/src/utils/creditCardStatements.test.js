import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { shouldLoadStatements } from './creditCardRepayment'

// 「全部账单」对账视图的关键接线。项目无 @vue/test-utils：可提取的逻辑用
// 纯函数行为测试（shouldLoadStatements），组件间接线用源码结构断言锁定。
const LIST_SOURCE = readFileSync(
  fileURLToPath(new URL('../components/credit-cards/CreditCardStatementList.vue', import.meta.url)),
  'utf-8'
)
const VIEW_SOURCE = readFileSync(
  fileURLToPath(new URL('../views/CreditCards.vue', import.meta.url)),
  'utf-8'
)

describe('shouldLoadStatements（加载守卫，行为测试）', () => {
  it('全局模式无条件加载（不需要 cardId）', () => {
    expect(shouldLoadStatements(true, null)).toBe(true)
    expect(shouldLoadStatements(true, 1)).toBe(true)
  })
  it('单卡模式必须有 cardId 才加载（undefined/null 都不发请求）', () => {
    expect(shouldLoadStatements(false, 1)).toBe(true)
    expect(shouldLoadStatements(false, null)).toBe(false)
    expect(shouldLoadStatements(false, undefined)).toBe(false)
  })
  it('两者皆缺不加载，也不能隐式回退到全局', () => {
    expect(shouldLoadStatements(false, null)).toBe(false)
  })
})

describe('全部账单模式隔离（数据来源分支）', () => {
  it('默认单卡模式保持原列表与明细接口路径', () => {
    // 单卡路径原样保留（详情弹窗仍走这两条）
    expect(LIST_SOURCE).toContain('`/api/credit-cards/${props.cardId}/statements`')
    expect(LIST_SOURCE).toContain('`/api/credit-cards/${props.cardId}/statements/${id}/items`')
  })

  it('仅显式 all 模式请求用户级账单接口', () => {
    expect(LIST_SOURCE).toContain("props.all\n      ? '/api/credit-cards/statements/all'")
    expect(LIST_SOURCE).toContain('`/api/credit-cards/statements/all/${id}/items`')
  })

  it('watch 使用守卫纯函数且 immediate（单卡首开必须加载——删除 immediate 会被此断言发现）', () => {
    expect(LIST_SOURCE).toContain('if (shouldLoadStatements(props.all, props.cardId)) load()')
    expect(LIST_SOURCE).toMatch(/immediate:\s*true/)
  })

  it('all 为显式布尔 prop 且默认关闭（不能缺 cardId 就隐式切全局）', () => {
    expect(LIST_SOURCE).toMatch(/all:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/)
  })
})

describe('孤立账单身份与联动', () => {
  it('孤立判定仅在全局模式且严格 card_name === null（单卡接口无该字段不得误标）', () => {
    expect(LIST_SOURCE).toContain('props.all && s.card_name === null')
  })

  it('全局行渲染身份列，单卡模式不渲染', () => {
    expect(LIST_SOURCE).toContain('v-if="all" class="stmt-owner"')
  })

  it('父级回调：applyCardUpdate 在 refreshOutstanding 之前且中间无条件返回（card:null 仍刷汇总）', () => {
    // 锁语句顺序而非仅锁存在：applyCardUpdate 与 await refreshOutstanding 之间
    // 插入 `if (!updatedCard) return` 这类提前返回时，顺序断言失败
    const fnStart = VIEW_SOURCE.indexOf('async function onAllStatementsChanged')
    const fnBody = VIEW_SOURCE.slice(fnStart, fnStart + 600)
    const applyPos = fnBody.indexOf('applyCardUpdate(updatedCard)')
    const refreshPos = fnBody.indexOf('await refreshOutstanding()')
    expect(applyPos).toBeGreaterThanOrEqual(0)
    expect(refreshPos).toBeGreaterThan(applyPos)
    // 两者之间不得有 return（提前返回会让孤立账单跳过汇总刷新）
    const between = fnBody.slice(applyPos + 'applyCardUpdate(updatedCard)'.length, refreshPos)
    expect(betterWithoutReturn(between)).toBe(true)
  })
  function betterWithoutReturn(text) {
    return !/\breturn\b/.test(text)
  }

  it('打开入口统一走 openAllStatements（新会话清理过期错误标记）', () => {
    expect(VIEW_SOURCE).toContain('function openAllStatements()')
    expect(VIEW_SOURCE).toContain('@click="openAllStatements"')
    expect(VIEW_SOURCE).toContain('@show-all-statements="openAllStatements"')
    // 不再有直接置 true 的散落入口
    expect(VIEW_SOURCE).not.toContain('allStatementsOpen = true"')
    expect(VIEW_SOURCE).not.toContain('@show-all-statements="allStatementsOpen = true"')
    // openAllStatements 必须重置 refreshFailed（否则过期告警在重开后仍显示）
    const fnBody = VIEW_SOURCE.slice(
      VIEW_SOURCE.indexOf('function openAllStatements()'),
      VIEW_SOURCE.indexOf('function openAllStatements()') + 260
    )
    expect(fnBody).toContain('allStatementsRefreshFailed.value = false')
    expect(fnBody).toContain('allStatementsOpen.value = true')
  })
})

describe('还款链路复用约束（泛化不破坏单卡行为）', () => {
  it('mutation 响应原位合并（不能整条替换——响应无 card_name 会丢身份）', () => {
    // 两处更新都必须是 Object.assign 合并，不能 statements.value[idx] = data.statement
    expect(LIST_SOURCE).toContain('Object.assign(statements.value[idx], data.statement)')
    expect(LIST_SOURCE).toContain('Object.assign(s, data.statement)')
    expect(LIST_SOURCE).not.toContain('statements.value[idx] = data.statement')
  })

  it('弹窗写操作 pending 上抛（外层禁止请求中关闭）', () => {
    // emit 必须由 watch(markPending) 驱动（finally 复位后自动发 false），不能是
    // 手工散落的单点 emit（漏发 false 会永久锁死弹窗）
    expect(LIST_SOURCE).toContain('watch(markPending, notifyPending)')
    expect(LIST_SOURCE).toContain("emit('pending-change', markPending.value)")
    expect(VIEW_SOURCE).toContain('@pending-change="allStatementsPending = $event"')
    expect(VIEW_SOURCE).toContain(':pending="allStatementsPending"')
  })

  it('还款弹窗目标名走 repayTargetName（全局模式带卡片身份）', () => {
    expect(LIST_SOURCE).toContain('name: repayTargetName(s)')
  })

  it('存活卡身份也带银行+尾号（同名卡区分，M2）', () => {
    // 锁存活卡分支的返回值必须引用 tail 模板（回归形态 `return s.card_name`
    // 单独出现即失败），且 tail 拼接在两个分支共用
    const fnStart = LIST_SOURCE.indexOf('const ownerLabel')
    const fnBody = LIST_SOURCE.slice(fnStart, fnStart + 480)
    const tailPos = fnBody.indexOf('const tail')
    const aliveReturn = fnBody.indexOf('if (s.card_name) return')
    expect(tailPos).toBeGreaterThanOrEqual(0)
    expect(aliveReturn).toBeGreaterThan(tailPos) // tail 先算，存活分支后用
    // 存活卡返回值必须是含 tail 的模板串，不能是裸 card_name
    expect(fnBody.slice(aliveReturn)).toMatch(/if \(s\.card_name\) return `\$\{s\.card_name\} · \$\{bank\}\$\{tail\}`/)
  })
})
