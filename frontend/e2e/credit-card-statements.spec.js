import { expect, test } from '@playwright/test'

// 「全部账单」跨卡对账视图：孤立账单可见可标记、汇总联动、单卡回归。
// 全部接口 mock（page.route），不依赖真实后端数据。

const username = process.env.E2E_ADMIN_USERNAME || 'e2e-admin'
const password = process.env.E2E_ADMIN_PASSWORD || 'e2e-admin-password-123'

async function login(page) {
  await page.goto('/login')
  const inputs = page.locator('.auth-card input')
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST'
  )
  await page.locator('.auth-card .btn').click()
  expect((await responsePromise).ok()).toBeTruthy()
  await expect(page).toHaveURL(/\/dashboard$/)
}

// _statement_out 形状的账单行（全局接口附加 card_name）
function stmt(overrides) {
  return {
    id: 1,
    bank_key: 'cmb',
    card_last_four: '6310',
    match_status: 'matched',
    bill_period_start: null,
    bill_period_end: null,
    statement_date: '2026-08-15',
    due_date: '2026-09-03',
    total_due: 800.5,
    min_due: null,
    credit_limit: null,
    subject: null,
    verify_status: 'ok',
    is_repaid: false,
    is_overdue: true,
    overdue_days: 15,
    repaid_at: null,
    repaid_amount: 0,
    remaining_amount: 800.5,
    parsed_at: '2026-08-15T10:00:00Z',
    item_count: 3,
    card_name: '招行主卡',
    ...overrides
  }
}

const outstanding = (total, overdue) => ({
  total,
  surplus_total: 0,
  unrepaid_count: 1,
  overdue_total: overdue,
  unknown_cycle_count: 0,
  per_card: [{ card_id: null, total_due: total, count: 1, cycles: [], overdue_cycles: [], max_overdue_days: overdue > 0 ? 15 : 0, unknown_cycle_count: 0, overdue_amount: overdue, is_surplus: false, latest_statement_id: null }]
})

test('零张信用卡仍能进入全部账单并登记还款孤立账单（card:null 不算失败）', async ({ page }) => {
  await login(page)
  let statements = [
    stmt({ id: 11, card_name: null, card_last_four: '8888', total_due: 300, remaining_amount: 300, is_overdue: false, overdue_days: null })
  ]
  let summary = outstanding(300, 0)
  let repayCalls = 0

  await page.route('**/api/credit-cards', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/credit-cards/outstanding/summary', (route) => route.fulfill({ json: summary }))
  await page.route('**/api/credit-cards/annual-fee/summary', (route) => route.fulfill({ json: { per_card: [] } }))
  await page.route('**/api/credit-cards/statements/all', (route) => route.fulfill({ json: { statements } }))
  // 明细接口：操作按钮只在明细加载成功后渲染
  await page.route('**/api/credit-cards/statements/all/11/items', (route) => route.fulfill({ json: { items: [], truncated: false } }))
  // 正金额账单（verify ok + 有剩余）走 POST /repay 登记还款弹窗，不是 PATCH——
  // 与真实后端分派一致（credit_cards.py repay 端点）
  await page.route('**/api/credit-cards/statements/11/repay', async (route) => {
    expect(route.request().method()).toBe('POST')
    repayCalls += 1
    const body = route.request().postDataJSON()
    // 真实 mutation 响应经 _statement_out 构造、不含 card_name——
    // 前端必须靠原位合并保留行身份，mock 同样剥掉以锁住该语义
    const mutated = { ...statements[0], repaid_amount: 300, is_repaid: true, remaining_amount: 0 }
    delete mutated.card_name
    const statement = mutated
    statements = statements.map((s) => (s.id === 11 ? { ...s, is_repaid: true, repaid_amount: 300, remaining_amount: 0 } : s))
    summary = outstanding(0, 0)
    await route.fulfill({ json: { ok: true, is_repaid: true, remaining_amount: 0, repaid_amount: Number(body.amount), auto_marked: 0, card: null, statement } })
  })

  await page.goto('/credit-cards')
  await page.getByRole('button', { name: '全部账单', exact: true }).click()
  // AppModal 标题与列表内部 strong 同文——用 dialog role 取唯一标题
  await expect(page.getByRole('dialog')).toContainText('全部账单（跨卡对账）')
  await expect(page.getByText('已删卡 / 未关联').first()).toBeVisible()

  // 展开孤立账单行 → 明细加载 → 操作按钮出现 → 登记还款弹窗 → 确认
  await page.getByRole('button', { name: /26年8月账单/ }).click()
  await page.getByRole('button', { name: '标记已还款' }).click()
  await page.getByRole('button', { name: '确认还款' }).click()

  expect(repayCalls).toBe(1)
  await expect(page.getByRole('button', { name: '取消还款标记' })).toBeVisible()
  // 汇总被刷新（还清后 total 变 0 → 统计卡展示 0）；card:null 不算失败
  await expect(page.getByRole('button', { name: /待还款总额/ })).toContainText('0')
  // 原位合并生效：mutation 响应不含 card_name，行身份仍显示
  await expect(page.getByText('已删卡 / 未关联').first()).toBeVisible()
})

test('全部账单保留跨卡、已还与孤立记录及服务端顺序，并展示口径说明', async ({ page }) => {
  await login(page)
  const statements = [
    stmt({ id: 21, card_name: '招行主卡', statement_date: '2026-08-15' }),
    stmt({ id: 22, card_name: null, card_last_four: '8888', bank_key: 'pab', is_repaid: true, repaid_amount: 120, is_overdue: false, overdue_days: null, statement_date: '2026-07-15' })
  ]
  await page.route('**/api/credit-cards', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/credit-cards/outstanding/summary', (route) => route.fulfill({ json: outstanding(800.5, 800.5) }))
  await page.route('**/api/credit-cards/annual-fee/summary', (route) => route.fulfill({ json: { per_card: [] } }))
  await page.route('**/api/credit-cards/statements/all', (route) => route.fulfill({ json: { statements } }))

  await page.goto('/credit-cards')
  await page.getByRole('button', { name: '全部账单', exact: true }).click()
  // 存活卡名 + 孤立标识 + 已还徽标 + 口径说明，全部可见
  await expect(page.getByText('招行主卡')).toBeVisible()
  await expect(page.getByText('已删卡 / 未关联').first()).toBeVisible()
  await expect(page.getByText('已还', { exact: true })).toBeVisible()
  await expect(page.getByText(/各期金额不可直接相加/)).toBeVisible()
  // 服务端顺序：26年8月在 26年7月 之前
  const periods = await page.locator('.stmt-period').allTextContents()
  expect(periods.indexOf('26年8月账单')).toBeLessThan(periods.indexOf('26年7月账单'))
})

test('单卡详情仍使用卡片级接口（泛化不破坏原路径）', async ({ page }) => {
  await login(page)
  const cardPaths = []
  await page.route('**/api/credit-cards', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/credit-cards/outstanding/summary', (route) => route.fulfill({ json: outstanding(0, 0) }))
  await page.route('**/api/credit-cards/annual-fee/summary', (route) => route.fulfill({ json: { per_card: [] } }))
  await page.route(/\/api\/credit-cards\/1\/statements$/, async (route) => {
    cardPaths.push(route.request().url())
    await route.fulfill({ json: { statements: [stmt({ id: 31, card_name: undefined })], unmatched_count: 0 } })
  })
  await page.route('**/api/credit-cards/statements/all', async () => {
    // 单卡详情不得误走全局接口
    throw new Error('single-card view must not call /statements/all')
  })

  // 单卡路径需要卡片存在才能开详情——直接注入列表数据
  await page.route('**/api/credit-cards', (route) => route.fulfill({ json: [{
    id: 1, display_name: '招行主卡', bank_name: '招商银行', last_four: '6310', statement_day: 15, due_day: 3,
    remind_days_before: [], credit_limit: null, is_active: true, show_in_calendar: true, repaid_through_due: null,
    fee_waiver_anchor_date: null, fee_waiver_target_count: null, fee_waiver_target_amount: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    next_statement_date: '2026-09-15', next_due_date: '2026-10-03', days_until_due: 15,
    statement_to_due_days: 18, interest_free_days: 46, interest_free_due_date: '2026-10-03'
  }] }))
  await page.goto('/credit-cards')
  await page.getByRole('button', { name: '查看详情' }).click()
  await expect(page.getByText('账单明细')).toBeVisible()
  expect(cardPaths.length).toBe(1)
})
