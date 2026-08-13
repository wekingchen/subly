import { expect, test } from '@playwright/test'

const username = process.env.E2E_ADMIN_USERNAME || 'e2e-admin'
const password = process.env.E2E_ADMIN_PASSWORD || 'e2e-admin-password-123'

async function login(page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.locator('.auth-card button[type="submit"]').click()
  await expect(page).toHaveURL(/\/dashboard$/)
}

test('路由标题、主标题和焦点随导航更新', async ({ page }) => {
  await login(page)
  await expect(page).toHaveTitle('雷达总览 · Subly')

  await page.getByRole('link', { name: '订阅账本' }).click()
  await expect(page).toHaveURL(/\/subscriptions$/)
  await expect(page).toHaveTitle('订阅账本 · Subly')
  await expect(page.locator('#main-content h1')).toHaveText('订阅账本')
  await expect(page.locator('#main-content h1')).toBeFocused()

  await page.getByRole('link', { name: '续费日历' }).click()
  await expect(page).toHaveTitle('续费日历 · Subly')
  const calendarHeading = page.locator('#main-content h1')
  await expect(calendarHeading).toHaveText('续费日历')
  await expect(calendarHeading).toBeFocused()
  const headingRect = await calendarHeading.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return { width: rect.width, height: rect.height }
  })
  expect(headingRect.width).toBeGreaterThan(0)
  expect(headingRect.height).toBeGreaterThan(0)
})

test('移动抽屉隔离背景、约束焦点并正确回焦', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)

  const menu = page.locator('.hamb')
  const sidebar = page.locator('#mobile-sidebar')
  const main = page.locator('#main-content')

  await expect(sidebar).toHaveAttribute('inert', '')
  await menu.click()
  await expect(menu).toHaveAttribute('aria-expanded', 'true')
  await expect(sidebar).toHaveAttribute('role', 'dialog')
  await expect(sidebar).toHaveAttribute('aria-modal', 'true')
  await expect(main).toHaveAttribute('inert', '')

  const close = page.getByRole('button', { name: '关闭导航菜单' })
  await expect(close).toBeFocused()
  await close.press('Shift+Tab')
  await expect(page.locator('.user a')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toHaveAttribute('aria-expanded', 'false')
  await expect(menu).toBeFocused()
  await expect(main).not.toHaveAttribute('inert', '')
})

test('文件导入保持单一键盘入口，家庭成员删除满足触控尺寸', async ({ page }) => {
  await login(page)
  await page.goto('/settings')
  const hiddenFileInputs = page.locator('input[type="file"][aria-hidden="true"]')
  await expect(hiddenFileInputs).toHaveCount(2)
  for (let index = 0; index < 2; index += 1) {
    await expect(hiddenFileInputs.nth(index)).toHaveAttribute('tabindex', '-1')
  }

  await page.goto('/subscriptions')
  await page.getByRole('button', { name: /添加订阅/ }).first().click()
  await page.getByLabel('成员名称').fill('尺寸验收成员')
  await page.getByRole('button', { name: '添加成员' }).click()
  const removeMember = page.getByRole('button', { name: '删除家庭成员“尺寸验收成员”' })
  const removeRect = await removeMember.evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return { width: rect.width, height: rect.height }
  })
  expect(removeRect.width).toBeGreaterThanOrEqual(44)
  expect(removeRect.height).toBeGreaterThanOrEqual(44)
})

test('登录表单与共享反馈暴露可访问语义', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByLabel('用户名')).toHaveAttribute('autocomplete', 'username')
  await expect(page.getByLabel('密码')).toHaveAttribute('autocomplete', 'current-password')

  let requests = 0
  await page.route('**/api/auth/login', async (route) => {
    requests += 1
    await new Promise((resolve) => setTimeout(resolve, 150))
    await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: '用户名或密码错误' }) })
  })
  await page.getByLabel('用户名').fill('invalid')
  await page.getByLabel('密码').fill('invalid')
  await page.getByLabel('密码').press('Enter')
  await page.getByLabel('密码').press('Enter')
  await expect(page.getByRole('alert')).toHaveText('用户名或密码错误')
  expect(requests).toBe(1)
})
