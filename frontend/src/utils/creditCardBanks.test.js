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
