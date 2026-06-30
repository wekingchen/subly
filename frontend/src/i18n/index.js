import { createI18n } from 'vue-i18n'

const zh = {
  app: { title: '省心订阅 Subly', tagline: '订阅 / 续费 / 保号，一个都不漏' },
  nav: { dashboard: '仪表盘', subscriptions: '订阅管理', calendar: '日历', reports: '报表分析', notifications: '通知中心', logs: '实时日志', settings: '设置', iconLibrary: '内置服务管理', users: '用户管理', logout: '退出', menu: '导航菜单', brandTag: '续费雷达' },
  notify: { title: '通知中心', runScan: '立即扫描提醒', empty: '暂无通知记录', sent: '已发送', failed: '失败', daysBefore: '提前天数' },
  rtlog: { title: '实时日志', live: '实时', paused: '已暂停', action: '操作', user: '用户', detail: '详情', time: '时间', empty: '暂无日志', auto: '自动刷新' },
  account: { title: '账号与密码', username: '用户名', email: '邮箱', saveAccount: '保存账号', changePwd: '修改密码', oldPwd: '原密码', newPwd: '新密码', pwdOk: '密码已修改', accountOk: '账号已更新' },
  sys: { title: '系统信息', version: '版本', dbStatus: '数据库', configured: '已连接', serverTime: '服务器时间', timezone: '时区', scanTime: '提醒扫描时间', yourSubs: '我的订阅', totalUsers: '用户总数', totalSubs: '订阅总数' },
  admin: {
    title: '用户管理', username: '用户名', email: '邮箱', role: '角色', admin: '管理员', user: '普通用户',
    status: '状态', active: '正常', disabled: '已禁用', subs: '订阅数', created: '注册时间',
    createUser: '新建用户', password: '密码', makeAdmin: '设为管理员', revokeAdmin: '取消管理员',
    enable: '启用', disable: '禁用', resetPwd: '重置密码', resetPwdPrompt: '输入新密码：',
    newPwdPh: '新密码', deleteTitle: '删除用户',
    confirmDelete: '确认删除该用户及其全部数据？', create: '创建', cancel: '取消',
    approved: '已通过', pending: '待审核', approve: '通过审核', emailUnverified: '邮箱未验证',
    pendingTab: '待审核 ({n})', allTab: '全部用户', noPending: '没有待审核的用户'
  },
  auth: {
    login: '登录', register: '注册', username: '用户名', email: '邮箱', password: '密码',
    loginBtn: '登录', registerBtn: '注册', noAccount: '没有账户？去注册', hasAccount: '已有账户？去登录',
    loginFail: '用户名或密码错误', welcome: '欢迎回来',
    verifyTitle: '邮箱验证', verifyTip: '验证码已发送至 {email}，请查收并填写（10 分钟内有效）',
    radarKicker: 'Renewal signal live', radarTitle: '续费雷达控制台',
    radarSubtitle: '把订阅、域名、VPS 和提醒通道放进自己的自托管雷达站。',
    radarScan: '30 天续费扫描', radarAlerts: 'Telegram + Bark 双通道', radarLedger: 'SQLite 本地账本',
    code: '验证码', codePh: '6 位数字', verifyBtn: '验证邮箱', backToLogin: '返回登录',
    pendingTitle: '等待审核', pendingMsg: '注册成功，正在等待管理员审核通过后即可登录。',
    registerOk: '注册成功，请登录'
  },
  dashboard: {
    monthSpend: '本月支出', yearSpend: '年度支出', active: '生效订阅', upcoming: '即将到期', recent: '最近订阅',
    none: '暂无数据', perMonth: '/月', daysLeft: '剩 {n} 天', today: '今天到期',
    overdue: '已过期', byCategory: '分类占比', avgMonth: '平均月支出', expiringSoon: '即将到期', viewAll: '查看全部',
    commandCenter: '控制台',
    greeting: '你好，{name} 👋', subtitle: '这是你的订阅总览', catOverview: '分类总览（全部订阅）',
    radarTitle: '续费雷达', radarHero: '未来 30 天有 {n} 项续费，预计 {amount}',
    radarOverdue: '已过期', radar3: '3 天内', radar7: '7 天内', radar30: '30 天内'
  },
  sub: {
    add: '添加订阅', edit: '编辑订阅', name: '名称', amount: '金额', currency: '货币',
    category: '分类', payment: '付款方式', billingType: '计费类型', recurring: '周期订阅', oneTime: '一次性买断',
    cycle: '周期', cycleCount: '每', day: '天', week: '周', month: '月', year: '年',
    startDate: '开始日期', nextRenewal: '下次续费', endDate: '结束日期', url: '链接', notes: '备注',
    remindDays: '提前提醒(天，逗号分隔)', active: '生效中', autoRenew: '自动续费',
    icon: '图标', save: '保存', cancel: '取消', delete: '删除', renew: '续费', confirmDelete: '确认删除该订阅？',
    uploadIcon: '上传图标', filterAll: '全部', filterRecurring: '周期', filterOneTime: '买断',
    plan: '套餐', planPh: '如 高级版 / 专业版',
    secService: '服务', secPrice: '价格信息', secBilling: '计费信息', secClassify: '分类与支付',
    secFamily: '家庭共享', secBundle: '捆绑包', secExtra: '附加信息', secCalendar: '日历',
    iconLibrary: '图标库', iconUrl: '图标 URL', iconUrlImport: '下载', nameSuggest: '常用服务（点击选择）',
    family: '家庭成员', familyAdd: '添加成员', familyPh: '成员名称',
    bundleNone: '不使用捆绑包', bundleJoin: '加入已有捆绑包', bundleCreate: '创建捆绑包', bundleName: '捆绑包名称',
    showInCalendar: '在日历中显示', website: '官方网站',
    browse: '按分类浏览', browseTitle: '选择服务', searchPh: '搜索服务名…', pickHint: '点击下方服务快速填入名称、图标与官网',
    renewTitle: '确认续费', renewMsg: '为「{name}」选择续费方式：',
    renewToday: '保号 / 提前续费：从今天起 +1 个周期（重新计周期）',
    renewDue: '常规循环：从原到期日 +1 个周期（不浪费已付时间）',
    renewNext: '续费后下次到期：', renewOk: '已续费，下次到期 {date}', confirm: '确认续费',
    expiredTag: '已过期', soonTag: '即将到期', uncategorized: '未分类', dragHint: '拖动卡片可排序，拖动分类标题可调整分类顺序',
    moveUp: '上移', moveDown: '下移', moreIcons: '显示更多图标',
    statusOverdue: '已过期', statusSoon: '即将到期', statusSafe: '安全', statusLifetime: '永久', lifetime: '永久买断',
    deleteTitle: '删除订阅', deletePwdTip: '为防止误删，请输入你的登录密码以确认删除「{name}」', pwdPh: '登录密码',
    remark: '个性化备注', remarkPh: '如：家庭主力机 / 香港 CN2（会显示在卡片上）',
    ipLabel: 'IP 地址（选填）', ipv4: 'IPv4', ipv6: 'IPv6'
  },
  calendar: {
    title: '续费日历', noEvents: '本月无续费', today: '今天', prevMonth: '上个月', nextMonth: '下个月', more: '还有 {n} 项',
    trajectory: '续费航迹', monthSignal: '本月信号', monthSummary: '本月 {n} 个续费信号，预计 {amount}', monthSafe: '本月暂无可见续费风险'
  },
  reports: {
    title: '报表分析', overview: '总览', insights: '支出洞察', categoryDetail: '分类明细', recentPayments: '近期付款',
    ranking: '支出排行', oneTime: '永久购买', upcoming: '即将续费', expired: '已过期',
    category: '分类', monthly: '月支出', percent: '占比', total: '月支出合计', empty: '暂无数据',
    monthlyTotal: '每月合计', yearlyTotal: '每年合计', byCategory: '分类支出占比', spendTrend: '支出概览',
    recurringSubs: '循环订阅', permanentBuy: '永久购买', count: '数量', amount: '金额', date: '日期', type: '类型',
    permanentTotal: '永久购买总额', recurringMonthly: '循环订阅月支出', noData: '暂无可视化数据',
    finRadar: '财务雷达', reportSubtitle: '支出结构、续费风险与近期付款信号', riskRadar: '续费压力', riskTotal: '风险信号',
    categorySignal: '分类信号', paymentSignal: '付款信号'
  },
  settings: {
    title: '设置', language: '语言', theme: '主题', baseCurrency: '基准货币', telegram: 'Telegram 通知',
    tgEnabled: '启用 Telegram 通知', botToken: 'Bot Token', adminId: 'Admin ID',
    apiBase: 'TG API 反代（可选）', proxy: 'HTTP 代理（可选）',
    chatId: 'Chat ID', botStatus: '机器人状态', checkBot: '验证机器人', testSend: '发送测试',
    getUpdates: '获取 Chat ID', save: '保存', saved: '已保存', refreshRates: '刷新汇率', ratesUpdated: '汇率已更新',
    themeLight: '浅色', themeDark: '深色', themeOcean: '海洋', themeForest: '森林', themePurple: '紫罗兰',
    botOk: '机器人正常', botFail: '验证失败', testOk: '测试消息已发送', logs: '通知记录',
    bark: 'Bark 推送', barkEnabled: '启用 Bark 推送', barkKey: 'Device Key',
    barkServer: '服务器地址（可选）', barkSound: '提示音（可选）', barkGroup: '分组（可选）', barkTtl: 'TTL（秒，可选）',
    barkTtlPh: '留空使用默认', barkTtlInvalid: 'TTL 必须是非负整数',
    barkTip: '在 iOS 上安装 Bark App，打开后复制你的 Device Key 填到下面即可（支持自建服务器）。',
    rateTable: '常用货币汇率', rateTip: '1 单位货币兑换为 {base} 的当日金额', updatedAt: '更新于', noRates: '暂无汇率数据，请点击「刷新汇率」'
  },
  backup: {
    title: '数据备份与恢复',
    tip: '把你的订阅及自定义分类/付款方式等导出为 JSON 离线保存；重新部署后导入即可恢复，避免数据丢失。',
    export: '导出备份', import: '导入恢复', replace: '导入前清空现有订阅',
    replaceConfirm: '将先删除你当前的全部订阅，再从备份导入。确定继续？',
    exportOk: '备份已下载', importOk: '已成功导入 {n} 个订阅', importFail: '导入失败：文件格式不正确'
  },
  backupAll: {
    title: '整站备份与恢复（管理员）',
    tip: '导出全部成员的账户与数据为一个 JSON 文件；重新部署后导入即可整站恢复所有用户的订阅、分类等。',
    export: '导出整站备份', import: '导入整站恢复', replace: '每个用户导入前清空其现有订阅',
    importConfirm: '将从整站备份恢复全部成员数据（缺失的账户会自动重建）。确定继续？',
    replaceConfirm: '将先清空每个用户的全部订阅，再从整站备份导入。确定继续？',
    exportOk: '整站备份已下载（{n} 个用户）', importOk: '已恢复 {users} 个用户（新建 {created} 个），共导入 {n} 个订阅'
  },
  iconLib: {
    title: '内置服务管理', subtitle: '管理服务清单、分类与图标缓存',
    add: '新增服务', edit: '编辑', fetchOne: '抓取图标', fetchMissing: '预热缺失图标', fetchAll: '全部重新抓取',
    running: '正在抓取…', done: '完成', total: '总数', cached: '已缓存', missing: '未缓存',
    active: '启用', inactive: '已停用', activate: '启用', deactivate: '停用', builtin: '内置', custom: '自定义',
    name: '名称', domain: '域名', website: '官网', category: '分类', slug: 'Slug', status: '状态', source: '来源',
    sort: '排序', icon: '图标', actions: '操作',
    searchPh: '搜索名称 / 域名 / slug…', filterAll: '全部', filterCached: '已缓存', filterMissing: '未缓存',
    filterActive: '启用', filterInactive: '已停用',
    confirmDeactivate: '确认停用该服务？（旧订阅图标仍可显示）',
    confirmFetchAll: '将对所有服务重新抓取图标，可能耗时较长。继续？',
    formTitleNew: '新增服务', formTitleEdit: '编辑服务', namePh: '如 Netflix', domainPh: '如 netflix.com',
    websitePh: '留空用 https://域名', categoryPh: '选择分类', categoryMultiHint: '可选择多个分类；第一个分类会作为兼容主分类', slugPh: '留空自动生成', slugWarn: '修改 slug 会影响旧订阅图标地址',
    save: '保存', cancel: '取消', saveOk: '已保存', deleteOk: '已停用', activateOk: '已启用',
    fetchOk: '已抓取', fetchFail: '抓取失败', progress: '进度', success: '成功', failed: '失败', skipped: '跳过',
    current: '当前', noJobs: '暂无抓取任务', details: '明细', provider: '来源', errReason: '原因',
    nameReq: '请填写名称', domainReq: '请填写域名', categoryReq: '请至少选择一个分类', slugExists: 'slug 已存在', okCount: '成功 {ok}', failCount: '失败 {fail}',
    overview: '概览', cachedCount: '{n} 已缓存', missingCount: '{n} 未缓存', activeCount: '{n} 启用', inactiveCount: '{n} 停用',
    exportList: '导出列表', refresh: '刷新', batch: '批量', selectAll: '全选', batchFetch: '抓取所选'
  },
  common: { loading: '加载中...', save: '保存', actions: '操作', status: '状态', date: '日期', confirm: '确认', cancel: '取消', close: '关闭' }
}

export default createI18n({
  legacy: false,
  locale: 'zh',
  fallbackLocale: 'zh',
  messages: { zh }
})
