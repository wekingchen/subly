// 国内常见银行品牌映射（首期 5 家）：前端静态数据，无网络请求，离线可用。
// logo 字段预留真实商标路径（src/assets/banks/），为空时徽标组件用品牌色 + short 字。
export const BANK_BRANDS = {
  cmb: { name: '招商银行', slug: 'cmbchina_com', short: '招', color: '#C8102E', logo: '', aliases: ['招商', '招商银行', '招行', '招商银行股份有限公司', '招商信用卡', '招商银行信用卡', 'cmb', 'china merchants'] },
  pab: { name: '平安银行', slug: 'pingan_com', short: '平', color: '#F58220', logo: '', aliases: ['平安', '平安银行', '平安银行股份有限公司', '平安信用卡', '平安银行信用卡', 'pab', 'ping an'] },
  cmbc: { name: '民生银行', slug: 'cmbc_com_cn', short: '民', color: '#0066B3', logo: '', aliases: ['民生', '民生银行', '中国民生银行', '民生银行股份有限公司', '民生信用卡', '民生银行信用卡', 'cmbc', 'minsheng'] },
  citic: { name: '中信银行', slug: 'citicbank_com', short: '中', color: '#C7000B', logo: '', aliases: ['中信', '中信银行', '中信银行股份有限公司', '中信信用卡', '中信银行信用卡', 'citic', 'china citic'] },
  ccb: { name: '建设银行', slug: 'ccb_com', short: '建', color: '#0A6DA4', logo: '', aliases: ['建设', '建设银行', '建行', '中国建设银行', '建设信用卡', '建设银行信用卡', 'ccb', 'china construction'] }
}

const INDEX = new Map()
for (const [key, brand] of Object.entries(BANK_BRANDS)) {
  for (const alias of brand.aliases) INDEX.set(alias.toLowerCase(), key)
}

export function matchBankBrand(bankName) {
  if (typeof bankName !== 'string') return null
  const trimmed = bankName.trim().toLowerCase()
  if (!trimmed) return null
  const key = INDEX.get(trimmed)
  if (key) return { key, ...BANK_BRANDS[key] }
  // 用户常写变体：「中国招商银行」「招商银行股份」「平安银行股份有限」。
  // 剥离常见前后缀后重查，仍不命中才回退 null（不猜测未收录银行）。
  const stripped = trimmed
    .replace(/^中国/, '')
    .replace(/(股份有限公司|股份|银行)+$/g, '')
  const strippedKey = INDEX.get(stripped)
  return strippedKey ? { key: strippedKey, ...BANK_BRANDS[strippedKey] } : null
}
