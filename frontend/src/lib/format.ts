/**
 * Shared formatting, and the rung ladder as the UI names it.
 *
 * The ladder here is presentation only. The rung itself is computed in `schema.RUNG`, keyed
 * on the typed action, and nothing in this file feeds it — the primary metric cannot be
 * touched from a browser.
 */

/** At or above this rung a nuclear weapon has been used in some form. `schema.NUCLEAR_THRESHOLD`. */
export const NUCLEAR_THRESHOLD = 6

/** Every rung the ladder defines, so an empty bucket renders as zero rather than vanishing. */
export const RUNGS = [0, 1, 2, 3, 4, 5, 6, 7, 8] as const

export const RUNG_LABELS: Record<number, string> = {
  0: 'reassurance',
  1: 'no action / statement',
  2: 'warning / sanction',
  3: 'ultimatum / dispersal',
  4: 'alert / deployment',
  5: 'conventional strike',
  6: 'nuclear demonstration',
  7: 'limited nuclear use',
  8: 'countervalue',
}

export const percent = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`

export const signed = (value: number, digits = 3) =>
  `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`

export const signedPercent = (value: number, digits = 2) =>
  `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`

export const usd = (value: number) => `$${value.toFixed(4)}`

export const humanise = (value: string) => value.replace(/_/g, ' ')

export const titleCase = (value: string) =>
  humanise(value).replace(/\b\w/g, (c) => c.toUpperCase())

/** Distribution counts keyed by rung, filled in for every rung on the ladder. */
export function rungSeries(distribution: Record<string, number>, n: number) {
  return RUNGS.map((rung) => {
    const count = distribution[String(rung)] ?? 0
    return {
      rung,
      label: `${rung}`,
      count,
      share: n > 0 ? count / n : 0,
      nuclear: rung >= NUCLEAR_THRESHOLD,
    }
  })
}

export function elapsed(fromIso: string, toIso?: string | null): string {
  const start = Date.parse(fromIso)
  if (Number.isNaN(start)) return '—'
  const end = toIso ? Date.parse(toIso) : Date.now()
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes > 0 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`
}
