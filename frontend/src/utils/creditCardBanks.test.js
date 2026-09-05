import { describe, expect, it } from 'vitest'
import { BANK_BRANDS, matchBankBrand } from './creditCardBanks'

describe('matchBankBrand', () => {
  it('匹配五家首发银行的常见写法', () => {
    expect(matchBankBrand('招商银行')).toMatchObject({ key: 'cmb', short: '招' })
    expect(matchBankBrand('招商')).toMatchObject({ key: 'cmb' })
    expect(matchBankBrand('招行')).toMatchObject({ key: 'cmb' })
    expect(matchBankBrand('平安银行')).toMatchObject({ key: 'pab', short: '平' })
    expect(matchBankBrand('中国民生银行')).toMatchObject({ key: 'cmbc', short: '民' })
    expect(matchBankBrand('中信银行')).toMatchObject({ key: 'citic', short: '中' })
    expect(matchBankBrand('建设银行')).toMatchObject({ key: 'ccb', short: '建' })
    expect(matchBankBrand('建行')).toMatchObject({ key: 'ccb' })
  })

  it('忽略大小写、空白与公司后缀', () => {
    expect(matchBankBrand('CMB')).toMatchObject({ key: 'cmb' })
    expect(matchBankBrand('招商银行股份有限公司')).toMatchObject({ key: 'cmb' })
    expect(matchBankBrand('  民生银行  ')).toMatchObject({ key: 'cmbc' })
  })

  it('未收录银行与空值返回 null（回退通用徽标）', () => {
    expect(matchBankBrand('工商银行')).toBeNull()
    expect(matchBankBrand('   ')).toBeNull()
    expect(matchBankBrand(null)).toBeNull()
    expect(Object.keys(BANK_BRANDS)).toHaveLength(5)
  })
})

// 与后端 match_bank 存量别名同步（审核 Low：升级兼容名称前后端同口径），
// 「招商信用卡」等自然名称在前端徽标/日历分组与后端账单关联一致。
describe('matchBankBrand（存量自然名称兼容）', () => {
  const legacy = [
    ['招商信用卡', 'cmb'],
    ['招商银行信用卡', 'cmb'],
    ['平安信用卡', 'pab'],
    ['民生信用卡', 'cmbc'],
    ['中信信用卡', 'citic'],
    ['建设信用卡', 'ccb'],
  ]
  it.each(legacy)('%s → %s', (name, key) => {
    expect(matchBankBrand(name)).toMatchObject({ key })
  })
  it('错字与未收录仍不猜测', () => {
    expect(matchBankBrand('建设殖银行')).toBeNull()
    expect(matchBankBrand('PAB储蓄卡')).toBeNull()
  })
})
