import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// 登录错误三分类（宿主机重启竞态实测教训）：账密错误（后端 401 透传）不得
// 吞掉服务异常（fetchMe 失败），否则「密码正确却提示账密错误」误导排查。
// 项目无组件测试基建，用源码静态断言锁接线。
const LOGIN_SOURCE = readFileSync(
  fileURLToPath(new URL('../views/Login.vue', import.meta.url)),
  'utf-8'
)
const STORE_SOURCE = readFileSync(
  fileURLToPath(new URL('../stores/auth.js', import.meta.url)),
  'utf-8'
)

describe('登录错误三分类', () => {
  it('fetchMe 失败被标记 serviceError（不伪装成账密错误）', () => {
    expect(STORE_SOURCE).toContain('error.serviceError = true')
  })

  it('登录页对 serviceError 显示独立文案（不落入 loginFail 兜底）', () => {
    expect(LOGIN_SOURCE).toContain('if (e.serviceError)')
    expect(LOGIN_SOURCE).toContain("t('auth.loginServiceError')")
  })

  it('后端 401 明细仍透传（真账密错误可见）', () => {
    expect(LOGIN_SOURCE).toContain("e.response?.data?.detail || t('auth.loginFail')")
  })
})
