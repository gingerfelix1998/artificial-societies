/**
 * Resolve cited passage ids to the text behind them.
 *
 * A citation is only checkable against the claim it was attached to if the passage can be
 * read. `RunRecord` stores the ids rather than the block — deliberately, because storing
 * the block would mean storing what went into a prompt — so the text is fetched separately
 * from the persona's own store.
 *
 * **An id that does not resolve is shown as unresolved, never hidden.** That is the
 * citation-integrity finding: the persona attributed a claim to a passage it was not given.
 */

import { useEffect, useState } from 'react'

import type { PassageLookup } from '../types/artsoc'

export interface ResolvedPassage {
  passage_id: string
  source: string
  section: string
  text: string
}

export interface Passages {
  byId: Map<string, ResolvedPassage>
  unresolved: Set<string>
  loading: boolean
}

/** Fetch every citation in one run, grouped by the persona whose store owns it. */
export function usePassages(citationsByPersona: Map<string, string[]>): Passages {
  const [byId, setById] = useState<Map<string, ResolvedPassage>>(new Map())
  const [unresolved, setUnresolved] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)

  // Keyed on the flattened request so an unchanged run does not refetch on every render.
  const key = [...citationsByPersona]
    .map(([persona, ids]) => `${persona}:${[...ids].sort().join('|')}`)
    .sort()
    .join('~')

  useEffect(() => {
    if (citationsByPersona.size === 0) return
    let stale = false
    setLoading(true)

    void (async () => {
      const resolved = new Map<string, ResolvedPassage>()
      const missing = new Set<string>()

      // One request per persona, because a passage is only ever resolved against the store
      // of the persona who cited it — the same one-store-per-persona rule the retriever
      // holds, kept in the reader so text cannot be shown under the wrong name.
      await Promise.all(
        [...citationsByPersona].map(async ([persona, ids]) => {
          try {
            const response = await fetch(
              `/api/passages/${encodeURIComponent(persona)}?ids=${encodeURIComponent(
                ids.join(','),
              )}`,
            )
            if (!response.ok) throw new Error(String(response.status))
            const body = (await response.json()) as PassageLookup
            for (const passage of body.passages) resolved.set(passage.passage_id, passage)
            for (const id of body.unresolved ?? []) missing.add(id)
          } catch {
            // A corpus that cannot be read is not a reason to blank the transcript. The
            // ids stay visible as unresolved, which is also how an invented one looks —
            // so the panel says which it could not check rather than implying they failed.
            for (const id of ids) missing.add(id)
          }
        }),
      )

      if (stale) return
      setById(resolved)
      setUnresolved(missing)
      setLoading(false)
    })()

    return () => {
      stale = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return { byId, unresolved, loading }
}

/** Group a run's citations by the persona who made them. */
export function citationsByPersona(
  opinions: { persona_id: string; citations?: string[] }[],
): Map<string, string[]> {
  const grouped = new Map<string, Set<string>>()
  for (const opinion of opinions) {
    for (const citation of opinion.citations ?? []) {
      const set = grouped.get(opinion.persona_id) ?? new Set<string>()
      set.add(citation)
      grouped.set(opinion.persona_id, set)
    }
  }
  return new Map([...grouped].map(([persona, ids]) => [persona, [...ids]]))
}
