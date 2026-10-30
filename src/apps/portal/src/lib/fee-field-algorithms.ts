import type { PolicyQAFeeDecomposition, PolicyQAFeeDecompositionField } from './policy-qa-stream'

/** 工作台算法译文：只解释现有实现，不在浏览器计算金额或判断待遇资格。 */
export interface FeeFieldAlgorithm {
  meaning: string
  formula: string | null
  steps: string[]
  note?: string
}

const VERSIONS = new Set([
  'employee_outpatient_v1',
  'resident_outpatient_v1',
  'employee_outpatient_special_v1',
  'resident_outpatient_special_v1',
  'employee_special_fixed_kidney_v1',
])

/** 辅助核对行沿用字段中文主名，去掉实现中的英文算式后缀。 */
export function feeFieldDisplayLabel(field: PolicyQAFeeDecompositionField): string {
  const main = field.label.split('（')[0]
  if (field.fieldCode.endsWith('.detail')) return `${main}（明细汇总核对）`
  if (field.fieldCode === 'T_FeeAll.identity' || field.fieldCode === 'ZJE.identity') {
    return `${main}（医保内＋医保外核对）`
  }
  if (field.fieldCode.includes('.vs_fee_all_minus_fund')) return `${main}（总费用减基金核对）`
  if (field.fieldCode === 'XJZF.identity') return '现金与账户合计（账面核对）'
  return /[A-Za-z_]/.test(field.label) ? main : field.label
}

// 对应各链路 _build_fields、catalog_split、secondary_coverage 和 quota_reconciliations。
export function describeFeeField(
  field: PolicyQAFeeDecompositionField,
  context: PolicyQAFeeDecomposition,
): FeeFieldAlgorithm {
  const unknown: FeeFieldAlgorithm = {
    meaning: '这个字段的算法译文尚未补充，暂时只展示返回的金额和核对记录。',
    formula: null,
    steps: [],
  }
  if (!VERSIONS.has(context.algorithmVersion)) return unknown

  const code = field.fieldCode
  const base = code.split('.')[0]
  const special = context.algorithmVersion.includes('special')
  const resident = context.algorithmVersion.startsWith('resident_')
  const fixed = context.algorithmVersion === 'employee_special_fixed_kidney_v1'
  const name = (key: string, fallback: string) =>
    context.fields.find((item) => item.fieldCode === key)?.label ?? fallback
  const total = name(special ? 'ZJE' : 'T_FeeAll', '总费用')
  const inside = name(special ? (resident ? 'TSBYBN' : 'YBN') : 'T_FeeIn', '医保内费用')
  const outside = name(special ? (resident ? 'TSBYBW' : 'YBW') : 'T_FeeOut', '医保外费用')
  const first = name(special ? 'YBNQFJE' : 'T_FirstPay', '本次起付承担')
  const big = name(special ? 'DEGWYZHF' : 'T_BigPay', '大额支付')
  const bigSelf = name(special ? 'DEGWYZIF' : 'T_BigSelfPay', '大额个人自付')
  const retired = name(special ? 'BCZHF' : 'T_BCPay', '退休补助')
  const military = name(special ? 'JCZHF' : 'T_JCPay', '军残补助')
  const civil = name(special ? 'GFYLBCHBX' : 'T_OfficalPay', '公疗补助')
  const pool = name('TCZHF', '统筹基金支付')
  const poolSelf = name('TCZIF', '统筹自付')
  const db = name('BIG_ILL_PAY', '大病保险支付')
  const aid = name('CIVIL_IN', '医疗救助支付')
  const detail = '从本次每条费用明细的金额开始，退费按原记录的负数参与计算。'
  const split = special && !resident
    ? `分别汇总明细已经记录的医保内金额、医保外金额和先行自付；本链路不重新判断每项目录归类。`
    : '按费用发生日期匹配药品、诊疗或材料目录，逐项处理纳入范围、限价和先行负担比例，再汇总。'
  const starting = [detail, split]
  const deductible = `${inside}先扣除本次尚需承担的起付金额，剩余部分再进入基金支付计算。`
  const noBenefit = context.uncertainties.some(
    (item) => item.code === 'NO_BENEFIT_REASON_SEMANTICS_UNCONFIRMED',
  )
  const bigillChannel = context.calculations.some(
    (item) => item.formulaId === 'resident_bigill_pay_v1',
  )
  const serviceChannel = context.calculations.some(
    (item) => item.formulaId === 'resident_msf_full_pay_v1',
  )

  if (code.endsWith('.detail')) {
    return {
      meaning: '将收费明细中已经记录的对应金额相加，用来核对结算汇总。',
      formula: `${field.label}＝各条费用明细中对应金额之和`,
      steps: [detail, '读取每条明细已有的对应金额，相加后与结算单比较。'],
      note: '这一步只核对加总关系，不证明每条明细的归类或待遇计算正确。',
    }
  }
  if (code === 'QUOTA.balance') {
    return {
      meaning: '核对医院定额、医院垫付与个人支付是否平衡。',
      formula: `${name('QUOTA_AMOUNT', '医院核定定额')}＝${name('AGENCY_PAY', '医院垫付基金合计')}＋${name('XJZF', '现金支付')}＋${name('ZHZF', '账户支付')}－${outside}`,
      steps: [...starting, '分开保留实际收费和医院核定定额，再用结算记录的垫付、账户、现金及医保外金额核对定额。'],
      note: '这是医院定额的账面核对，不能用来证明患者实际个人应付。',
    }
  }
  if (code.endsWith('.identity') || code.includes('.vs_fee_all_minus_fund')) {
    const isTotal = base === 'T_FeeAll' || base === 'ZJE'
    return {
      meaning: '用结算单已有金额核对加减关系，不是从明细独立重算。',
      formula: isTotal
        ? `${total}＝${inside}＋${outside}`
        : fixed
          ? `现金支付＋账户支付＝医院核定定额＋${outside}－各项基金及补助支付`
          : special
            ? `现金支付＋账户支付＝${total}－各项基金及补助支付`
            : `${name('T_SelfPayAll', '最终个人承担')}＝${total}－${name('T_FundPay', '基金合计')}`,
      steps: [detail, '明细形成费用总额和各项支付后，再读取结算单的对应汇总金额核对等式。'],
      note: '等式相符只能证明账面关系相符，不能代替项目归类、比例和资格的核实。',
    }
  }
  if (noBenefit && ['T_FeeIn', 'T_FeeOut', 'T_SelfPay2', 'T_FirstPay', 'T_BigPay', 'T_BigSelfPay', 'T_BCPay', 'T_JCPay', 'T_OfficalPay'].includes(code)) {
    return {
      meaning: '本单进入当前代码的全额个人承担分支，没有继续计算普通门诊基金支付。',
      formula: `${field.label}＝${code === 'T_FeeOut' ? '费用明细金额合计' : '0 元'}`,
      steps: [detail, '根据结算中的全额个人承担标记，全部费用计入医保外，其余上述费用及基金项记为零。'],
      note: '该标记的业务含义仍待确认；不能据此断言药品属于目录外或患者不享受医保待遇。',
    }
  }

  switch (code) {
    case 'T_FeeAll':
    case 'ZJE':
      return {
        meaning: '这笔结算所有收费项目的金额合计。',
        formula: `${field.label}＝各条费用明细金额之和`,
        steps: [detail, '把本次纳入结算的明细金额逐条相加，与结算总额核对。'],
      }
    case 'T_FeeIn':
    case 'YBN':
    case 'TSBYBN':
      return {
        meaning: '纳入医保计算的费用基数，还需要继续计算起付和个人分担，并不等于基金支付。',
        formula: `${field.label}＝各条费用明细的医保内金额之和`,
        steps: [...starting, special && !resident
          ? '直接合计明细中已记录的医保内金额，再与结算汇总核对。'
          : '逐项从费用金额中扣除不纳入部分及先行自付，合计剩余医保内金额。'],
      }
    case 'T_FeeOut':
    case 'YBW':
    case 'TSBYBW':
      return {
        meaning: '没有进入医保内费用基数的部分，包含本链路记录的先行自付。',
        formula: bigillChannel
          ? `${field.label}＝不纳入费用＋大病支付后剩余的比例先行自付`
          : `${field.label}＝各条费用明细的医保外金额之和`,
        steps: [...starting, bigillChannel
          ? '本单使用居民大病通道：不纳入费用加上大病支付后剩余的比例先行自付，形成结算医保外金额。'
          : '逐项汇总不纳入费用、超过纳入限额的部分及先行自付，形成医保外金额。'],
        note: '自付二已包含在医保外费用中，计算个人承担时不能再加一次；救助冲抵等未确认口径保留核对缺口。',
      }
    case 'T_SelfPay2':
    case 'GRZIFTW':
      return {
        meaning: '项目进入医保支付计算之前，需要个人先行负担的费用合计。',
        formula: `${field.label}＝各条费用明细的先行自付金额之和`,
        steps: [...starting, bigillChannel
          ? '本单使用居民大病通道：先计算目录比例先行自付，再保留大病支付后由个人承担的部分。'
          : '按每项的先行负担及限价规则计算；职工门特项目链路直接汇总明细中已记录的先行自付。'],
        note: '二次保障只采用其中符合范围的按比例先行自付，不把所有全额自费或超限额部分都纳入。',
      }
    case 'T_FirstPay':
    case 'YBNQFJE':
      return {
        meaning: '本次费用中用于补足起付标准、先由个人承担的部分。',
        formula: serviceChannel || bigillChannel
          ? `${field.label}＝0 元（本单专门通道不收取门诊起付）`
          : `${field.label}＝${inside}与“起付标准尚未补足金额”中的较小值`,
        steps: [...starting, `确认${special ? '特殊病结算周期' : '年度'}在本次之前的起付累计，算出还差多少。`,
          serviceChannel || bigillChannel
            ? '本单走医事服务费或居民大病通道，当前代码不收取这项门诊起付，记为零。'
            : `从本次${inside}中补足剩余起付；已达到标准时本次不再承担。`],
        note: '缺少累计或周期时不能默认已经达到起付线；采用账面起付作条件输入时也不算独立重算。',
      }
    case 'T_BigPay':
    case 'DEGWYZHF':
      return {
        meaning: resident && special ? '居民门特由基本医保基金支付的部分。' : '费用进入大额支付阶段后，由该基金支付的部分。',
        formula: fixed
          ? `${field.label}＝医院核定定额－定额范围内原始自付一（含起付）－${pool}`
          : serviceChannel
            ? `${field.label}＝限额内医保内费用×100%`
            : bigillChannel
              ? `${field.label}＝0 元（本单走大病支付通道）`
              : `${field.label}＝各支付段费用×对应支付比例，再按剩余额度限制支付`,
        steps: [...starting, deductible, fixed
          ? '患者实际自付按降低后的比例计算；医院基金以核定定额减原始自付，先计入统筹，余下计入大额，并检查限额。'
          : special && !resident
            ? '先完成统筹支付；进入大额阶段的费用再按对应比例计算，并检查年度剩余支付限额。'
            : serviceChannel
              ? '本单医事服务费通道按限额内医保内费用全额支付。'
              : bigillChannel
                ? '本单使用居民大病通道，大额支付记零，不与大病支付重复计算。'
                : '结合人员、机构和本次之前的累计确定比例；跨段分别计算，支付不超过剩余限额。'],
      }
    case 'T_BigSelfPay':
    case 'DEGWYZIF':
      return {
        meaning: '进入该支付阶段的费用中，基金支付后仍需个人分担的部分。',
        formula: fixed
          ? `${field.label}＝患者实际大额段费用×降低后的个人自付比例（最低为零）`
          : bigillChannel || serviceChannel
            ? `${field.label}＝0 元（本单专门支付通道）`
            : `${field.label}＝该阶段费用－${big}`,
        steps: [...starting, deductible, '先计算该阶段基金支付，再用该阶段费用扣除基金支付；补助在后续另行处理。'],
        note: fixed ? '患者自付按实际费用计算；不得拿医院定额基金直接从实际总费用中扣减。' : '医事服务费或居民大病专门通道按各自分支处理；部分救助口径尚不能直接核对。',
      }
    case 'TCZHF':
    case 'TCZIF':
      return {
        meaning: code === 'TCZHF' ? '统筹阶段由基金支付的部分。' : '统筹阶段中基金支付后，留待个人分担或后续补助的部分。',
        formula: resident
          ? `${field.label}＝0 元（当前居民门特链路不设这两个统筹项目）`
          : fixed
            ? code === 'TCZHF'
              ? `${field.label}＝“医院核定定额减原始个人自付”与“统筹剩余额度”中的较小值`
              : `${field.label}＝患者实际统筹段费用×降低后的个人自付比例（最低为零）`
            : code === 'TCZHF'
            ? `${field.label}＝统筹各段费用×对应支付比例，再检查统筹剩余额度`
            : `${field.label}＝统筹阶段费用－患者口径的统筹基金支付`,
        steps: [...starting, deductible, resident
          ? '当前居民门特通过基本医保基金支付字段计算，不重复计入这两个统筹项目。'
          : fixed
            ? '实际费用按统筹个人自付比例降低两个百分点计算原始自付，比例最低为零；医院统筹支付另外按定额差额及限额分配。'
            : '结合本次之前的统筹累计和人员、医院档次，将本次跨段费用分别计算基金和个人份额。'],
        note: fixed ? '定额链路中，这两个字段分别来自医院基金口径和患者实际费用口径，不能简单互减。' : undefined,
      }
    case 'T_BCPay':
    case 'BCZHF':
    case 'T_JCPay':
    case 'JCZHF':
    case 'T_OfficalPay':
    case 'GFYLBCHBX': {
      const retirement = code === 'T_BCPay' || code === 'BCZHF'
      const veteran = code === 'T_JCPay' || code === 'JCZHF'
      return {
        meaning: `符合对应待遇条件时，对前面计算出的个人负担给予的${retirement ? '退休' : veteran ? '军残' : '公疗'}补助。`,
        formula: resident
          ? `${field.label}：当前居民链路不适用`
          : `${field.label}＝符合补助范围的个人负担×对应补助比例（按适用分段计算）`,
        steps: [...starting, deductible, '先算基金支付和个人分担，并确认本人的对应待遇资格。',
          resident ? '当前居民链路不套用职工的退休、军残或公疗补助。'
            : retirement ? `按适用统筹段及大额段分别计算${retired}，起付部分不直接套退休补助比例。`
              : veteran ? `在${retired}后，对符合军残补助范围的起付和共付段剩余个人负担计算补助。`
                : `在${retired}、${military}后，按公疗适用范围、比例和剩余限额计算，不默认覆盖全部起付或自费。`],
        note: fixed && !retirement && !veteran
          ? '定额公疗的计算基数按实际医保内费用与核定定额中较小者处理。'
          : '资格或规则不明确时，只展示结算记录；支付为零本身不能证明不享受待遇。',
      }
    }
    case 'T_SelfPay1':
      return {
        meaning: '医保内费用经相应基金抵扣后，在结算单中记录的个人自付一。',
        formula: bigillChannel
          ? `${field.label}＝${total}－大病保险支付－${outside}`
          : `${field.label}＝${inside}－${big}－${civil}`,
        steps: noBenefit
          ? [detail, '本单按全额个人承担标记处理，医保内及常规基金、补助按零计算。', '再读取结算单的医保内、大额支付和公疗补充支付，核对自付一。']
          : [...starting, '按本链路的账面定义，读取医保内、大额支付和公疗补充支付进行核对。'],
        note: '这个字段不能直接当成最终个人承担，也不能只用医保内减全部基金合计替代。',
      }
    case 'T_FundPay':
      return {
        meaning: '结算单记录的各基金支付合计，不含个人账户与现金支付。',
        formula: bigillChannel
          ? `${field.label}＝${name('T_BigillPay', '大病保险支付')}`
          : resident
            ? `${field.label}＝${big}＋本单其他已记录基金支付`
            : `${field.label}＝${big}＋${retired}＋${military}＋${civil}`,
        steps: [...starting, deductible, '分别完成各基金及补助计算，再核对已明确支付渠道的合计。'],
        note: '其他基金渠道是否完整尚未明确时，不把已有几项之和认定为完整基金总额。',
      }
    case 'T_BigillPay':
      return {
        meaning: '当前居民普通门诊专门通道中的大病保险支付。',
        formula: `${field.label}＝符合该通道的医保内费用及比例先行自付基数×通道支付比例`,
        steps: [...starting, '确认本单实际采用居民普通门诊大病通道，再按本通道的基数与比例计算。'],
        note: '与门特按年度起付、跨五万元分段计算的二次保障是两条算法，不能混用。',
      }
    case 'T_SelfPayAll':
      return {
        meaning: '这笔费用中最终记在个人一侧的金额，可以由个人账户或现金支付。',
        formula: bigillChannel
          ? `${field.label}＝${total}－${name('T_FundPay', '基金合计')}`
          : `${field.label}＝${first}＋${outside}＋${bigSelf}－${retired}－${military}－${civil}`,
        steps: noBenefit
          ? [detail, '本单按结算中的全额个人承担标记，跳过常规的目录分解和基金计算。',
            '合计明细金额，全部计入医保外费用；起付、大额阶段及常规基金补助按零计算。',
            '再用结算单中的起付、医保外、大额自付和补助金额核对最终个人承担。']
          : [...starting, deductible, '计算大额阶段支付和个人分担，再依次计算适用补助。',
            `将起付、医保外和大额个人自付相加，扣除补助；另与${total}减基金合计核对。`],
        note: noBenefit
          ? '全额个人承担标记的业务含义仍待确认，不能据此推断药品本身属于目录外。自付二不重复加入医保外费用；个人承担不等于现金支付。'
          : '自付二已经包含在医保外费用中，不重复相加；居民大病通道另以总费用减全部基金支付核对。个人承担不等于现金支付。',
      }
    case 'SELF_PAY_1':
    case 'GRZIF1':
      return {
        meaning: fixed ? '定额范围内按实际费用计算、尚未扣除各类补助的原始个人自付。' : '把起付和各共付阶段的个人份额相加得到的自付一。',
        formula: `${field.label}＝${first}＋${poolSelf}＋${bigSelf}`,
        steps: [...starting, deductible, fixed
          ? '统筹和大额阶段的个人自付比例分别降低两个、五个百分点，最低为零，按实际费用计算。'
          : '分别算出起付、统筹阶段自付和基本基金支付后自付，再相加。'],
        note: fixed ? '之后还需扣退休、军残、公疗、大病及救助；不能把原始自付直接当成最后应付。' : undefined,
      }
    case 'BIG_ILL_PAY':
    case 'FEEIN_DB_PAY':
    case 'FEEOUT_DB_PAY':
      return {
        meaning: '基本医保和补助处理后，对符合范围的剩余个人负担计算的大病保险支付。',
        formula: code === 'BIG_ILL_PAY'
          ? `${field.label}＝${name('FEEIN_DB_PAY', '自付一的大病支付')}＋${name('FEEOUT_DB_PAY', '比例先行自付的大病支付')}`
          : `${field.label}＝本笔分段大病支付×对应费用基数÷本笔大病合规费用基数`,
        steps: [...starting, '完成基本医保、退休、军残和公疗补助，取得剩余合规自付一及比例先行自付。',
          '结合交易前年度累计，分别确定本笔落在起付以下、起付以上五万元以内、超过该段的金额，按各段比例累加。',
          '按自付一和比例先行自付各自占本笔合规基数的份额分配支付，分别取整后相加；跨起付、跨段不能整笔乘一个固定比例。'],
        note: '累计时点、身份或基数不明确时不能独立计算；纯自费和不合规的超限额费用不纳入。',
      }
    case 'CIVIL_IN':
    case 'FEEIN_MAF_PAY':
    case 'FEEOUT_MAF_PAY':
      return {
        meaning: '大病保险支付后，对符合救助范围的剩余个人负担给予的医疗救助。',
        formula: code === 'CIVIL_IN'
          ? `${field.label}＝${name('FEEIN_MAF_PAY', '自付一的救助')}＋${name('FEEOUT_MAF_PAY', '比例先行自付的救助')}`
          : `${field.label}＝对应费用基数扣除大病支付后的剩余金额×救助比例，再限制在年度剩余额度内`,
        steps: [...starting, '先完成基本医保、各项补助和大病保险，再确认救助身份及适用比例。',
          '分别计算自付一和比例先行自付的剩余救助金额；有年度限额时按剩余额度同比缩减，并分配到分。'],
        note: '当前门特代码采用门特视同住院的救助档。非救助身份记零；封顶累计缺失不能按本笔账面救助金额倒推凑平。',
      }
    case 'PERSON_PAYABLE':
      return {
        meaning: '本次费用完成基本医保、各项补助、大病和救助后，剩余的个人应付。',
        formula: field.checkType === 'identity_check'
          ? `${field.label}＝${first}＋${poolSelf}＋${bigSelf}－${retired}－${military}－${civil}＋${outside}`
          : `${field.label}＝补助后合规自付一＋${outside}－${db}－${aid}`,
        steps: [...starting, deductible, '完成基本基金支付，依次扣退休、军残、公疗补助，得到合规自付一。',
          field.checkType === 'identity_check'
            ? '本行只是按结算单已有金额核对支付渠道；二次保障后的独立计算见同名的二次保障核对行。'
            : `加上全部医保外费用，再扣除${db}和${aid}，与现金及账户支付合计核对。`],
        note: fixed ? '按患者实际费用和自付计算，不能用实际总费用减医院定额垫付额替代。' : '医保外中已含先行自付，不再重复相加；个人应付与现金、账户如何分摊是两件事。',
      }
    case 'QUOTA_AMOUNT':
      return {
        meaning: '医院按定额结算使用的费用标准，与这笔实际收费分开记录。',
        formula: null,
        steps: [...starting, '确认定额病种、本人定点、用药时段及定额管理范围。', '当前代码将医院核定定额作为条件输入；日标准和按天分段规则尚未确认，不独立重算定额。'],
        note: '不能把实际明细金额当成定额，也不能用账面定额倒推出日标准。',
      }
    case 'AGENCY_PAY':
      return {
        meaning: fixed ? '医院垫付的各项基金和补助合计，使用医院定额口径。' : '结算中基本医保、大病、救助及其他已记录基金渠道的支付合计。',
        formula: `${field.label}＝${pool}＋${big}＋${retired}＋${military}＋${civil}＋${db}＋${aid}${fixed ? '' : '＋其他已记录基金渠道'}`,
        steps: [...starting, fixed
          ? '先用医院核定定额减原始个人自付，按统筹、大额顺序分配医院基金，再加上实际计算出的各项补助、大病和救助。'
          : '分别完成各基金及补助后相加，并与总费用扣除现金和账户支付的余额核对。'],
        note: fixed ? '医院定额与患者实际费用不同，这个合计不能直接用来计算患者个人应付。' : '账面相加不代表各支付渠道已经独立重算正确。',
      }
    case 'T_PersonCountPay':
    case 'T_CashPay':
    case 'ZHZF':
    case 'XJZF':
      return {
        meaning: code === 'T_PersonCountPay' || code === 'ZHZF' ? '结算记录中由个人账户支付的金额。' : '结算记录中由现金渠道支付的金额，不等于全部个人负担。',
        formula: null,
        steps: [detail, '费用分解先确定个人应付；账户与现金的实际分摊直接读取结算记录。', '当前缺少当时的账户扣款规则和完整支付流水，不从个人应付反推账户或现金金额。'],
        note: '没有独立重算算法；个人承担增加，不等于本次现金支付一定增加。',
      }
    default:
      return unknown
  }
}
