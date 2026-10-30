// 金额仅用于展示账面占比；不以占比倒推待遇规则或重算结算金额。
export function decimalUnits(value: string | null | undefined, scale = 6): bigint | null {
  if (!value || !/^-?\d+(\.\d+)?$/.test(value)) return null
  const [whole, fraction = ''] = value.replace('-', '').split('.')
  if (fraction.length > scale && /[1-9]/.test(fraction.slice(scale))) return null
  const units = BigInt(whole) * BigInt(10) ** BigInt(scale) + BigInt(fraction.slice(0, scale).padEnd(scale, '0'))
  return value.startsWith('-') ? -units : units
}

export function percentOf(part: string | null | undefined, total = '1'): string | null {
  const numerator = decimalUnits(part), denominator = decimalUnits(total)
  if (numerator === null || denominator === null || denominator <= BigInt(0) || numerator < BigInt(0) || numerator > denominator) return null
  const hundredths = (numerator * BigInt(10000) + denominator / BigInt(2)) / denominator
  return `${hundredths / BigInt(100)}${hundredths % BigInt(100) ? `.${String(hundredths % BigInt(100)).padStart(2, '0').replace(/0$/, '')}` : ''}%`
}

export function complementRatio(value: string | null | undefined): string | null {
  const units = decimalUnits(value)
  if (units === null || units < BigInt(0) || units > BigInt(1000000)) return null
  return `${(BigInt(1000000) - units) / BigInt(1000000)}.${String((BigInt(1000000) - units) % BigInt(1000000)).padStart(6, '0')}`
}

export function sumAmounts(values: (string | null | undefined)[]): string | null {
  const units = values.map((value) => decimalUnits(value))
  if (!units.length || units.some((value) => value === null)) return null
  const total = (units as bigint[]).reduce((sum, value) => sum + value, BigInt(0))
  const absolute = total < BigInt(0) ? -total : total
  const fraction = String(absolute % BigInt(1000000)).padStart(6, '0').replace(/0+$/, '')
  return `${total < BigInt(0) ? '-' : ''}${absolute / BigInt(1000000)}${fraction ? `.${fraction}` : ''}`
}
