const competitionNames: Record<string, string> = {
  E0: '英超',
  E1: '英冠',
  E2: '英甲',
  E3: '英乙',
  EC: '英格兰全国联赛',
  SC0: '苏超',
  SC1: '苏冠',
  SC2: '苏甲',
  SC3: '苏乙',
  D1: '德甲',
  D2: '德乙',
  I1: '意甲',
  I2: '意乙',
  SP1: '西甲',
  SP2: '西乙',
  F1: '法甲',
  F2: '法乙',
  N1: '荷甲',
  B1: '比甲',
  P1: '葡超',
  T1: '土超',
  G1: '希腊超',
  ARG: '阿根廷甲级联赛',
  AUT: '奥地利甲级联赛',
  BRA: '巴西甲级联赛',
  CHN: '中超',
  DNK: '丹麦超',
  FIN: '芬超',
  IRL: '爱尔兰超级联赛',
  JPN: '日职联',
  MEX: '墨西哥超级联赛',
  NOR: '挪威超',
  POL: '波兰甲级联赛',
  ROU: '罗马尼亚甲级联赛',
  RUS: '俄超',
  SWE: '瑞典超',
  SWZ: '瑞士超',
  USA: '美国职业足球大联盟',
}

const teamNames: Record<string, string> = {
  arsenal: '阿森纳',
  everton: '埃弗顿',
  liverpool: '利物浦',
  chelsea: '切尔西',
  'man united': '曼联',
  'man utd': '曼联',
  'manchester united': '曼联',
  'man city': '曼城',
  'manchester city': '曼城',
  tottenham: '托特纳姆热刺',
  'tottenham hotspur': '托特纳姆热刺',
  newcastle: '纽卡斯尔联',
  'newcastle united': '纽卡斯尔联',
  'west ham': '西汉姆联',
  'west ham united': '西汉姆联',
  'aston villa': '阿斯顿维拉',
  brighton: '布莱顿',
  'brighton & hove albion': '布莱顿',
  wolves: '狼队',
  'wolverhampton wanderers': '狼队',
  'crystal palace': '水晶宫',
  burnley: '伯恩利',
  "nott'm forest": '诺丁汉森林',
  'nottingham forest': '诺丁汉森林',
  fulham: '富勒姆',
  brentford: '布伦特福德',
  bournemouth: '伯恩茅斯',
  'afc bournemouth': '伯恩茅斯',
  leicester: '莱斯特城',
  'leicester city': '莱斯特城',
  leeds: '利兹联',
  'leeds united': '利兹联',
  southampton: '南安普顿',
  ipswich: '伊普斯维奇',
  sunderland: '桑德兰',
  birmingham: '伯明翰',
  middlesbrough: '米德尔斯堡',
  norwich: '诺维奇',
  stoke: '斯托克城',
  swansea: '斯旺西',
  cardiff: '卡迪夫城',
  'bayern munich': '拜仁慕尼黑',
  dortmund: '多特蒙德',
  'rb leipzig': '莱比锡红牛',
  leverkusen: '勒沃库森',
  'schalke 04': '沙尔克04',
  barcelona: '巴塞罗那',
  'real madrid': '皇家马德里',
  'atletico madrid': '马德里竞技',
  valencia: '瓦伦西亚',
  sevilla: '塞维利亚',
  juventus: '尤文图斯',
  inter: '国际米兰',
  milan: 'AC米兰',
  roma: '罗马',
  napoli: '那不勒斯',
  lazio: '拉齐奥',
  'paris sg': '巴黎圣日耳曼',
  marseille: '马赛',
  ajax: '阿贾克斯',
  'psv eindhoven': '埃因霍温',
  feyenoord: '费耶诺德',
  porto: '波尔图',
  benfica: '本菲卡',
  'sporting cp': '葡萄牙体育',
  celtic: '凯尔特人',
  rangers: '格拉斯哥流浪者',
  flamengo: '弗拉门戈',
  corinthians: '科林蒂安',
  santos: '桑托斯',
}

const marketTypeNames: Record<string, string> = {
  match_result: '胜平负',
  asian_handicap: '亚洲让球',
  handicap_result: '让球胜平负',
  over_under_2_5: '大小球（2.5）',
}

const outcomeNames: Record<string, string> = {
  home: '主胜',
  draw: '平',
  away: '客胜',
  over_2_5: '大于 2.5 球',
  under_2_5: '小于 2.5 球',
}

const sourceNames: Record<string, string> = {
  football_data: '公开足球数据',
  'football-data': '公开足球数据',
  legacy_unknown: '历史兼容数据',
  manual: '手工导入',
  sports_lottery: '体育彩票数据',
}

const providerNames: Record<string, string> = {
  average: '市场平均',
  williamhill: '威廉希尔',
}

const stageNames: Record<string, string> = {
  pre_match: '赛前',
  closing: '收盘',
}

const timePrecisionNames: Record<string, string> = {
  exact: '精确时间',
  date_only: '仅日期',
  kickoff_bound: '开球时间边界',
}

const importErrorNames: Record<string, string> = {
  timeout: '数据源请求超时',
  connection_error: '无法连接数据源',
  http_404: '数据文件不存在',
  http_429: '数据源请求过于频繁',
  http_500: '数据源暂时不可用',
  empty_content: '数据文件为空',
  html_content: '数据源返回了网页而不是数据文件',
  invalid_content_type: '数据文件格式不正确',
  invalid_encoding: '数据文件编码无法识别',
  missing_required_headers: '数据文件缺少必要字段',
  invalid_csv: '数据文件解析失败',
  unexpected_error: '导入过程中出现未分类错误',
}

function normalizeName(value: string): string {
  return value.normalize('NFKC').replace(/[’`]/g, "'").replace(/\s+/g, ' ').trim().toLowerCase()
}

export function competitionLabel(code: string, fallback = code): string {
  return competitionNames[code] ?? fallback
}

export function teamLabel(name: string): string {
  return teamNames[normalizeName(name)] ?? name
}

export function marketTypeLabel(value: string): string {
  return marketTypeNames[value] ?? value
}

export function outcomeLabel(value: string): string {
  return outcomeNames[value] ?? value
}

export function sourceLabel(value: string): string {
  return sourceNames[value] ?? value
}

export function providerLabel(value: string): string {
  return providerNames[value] ?? value
}

export function stageLabel(value: string): string {
  return stageNames[value] ?? value
}

export function timePrecisionLabel(value: string): string {
  return timePrecisionNames[value] ?? value
}

export function importErrorLabel(value: string): string {
  return importErrorNames[value] ?? '导入过程中出现未分类错误'
}
