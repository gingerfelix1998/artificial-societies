/**
 * The citizen audience (ADR 0009/0010): aggregated approval by stratum, and a way to open
 * a few of one segment's actual sampled citizens and continue talking to them.
 *
 * **The chart is arm-level; the citizens are this run's.** `metrics.audience_by_stratum` is
 * pooled across every replication of the arm that ran with an audience — more statistically
 * meaningful than one run's 70 citizens — but the citizens a segment opens onto are the
 * ones actually sampled in *this* representative run, since that is the only place their
 * individual profiles and recorded reactions are shipped to the browser at all.
 *
 * **Never a finding on its own.** The absolute approve share carries the same base-rate
 * confound the rung does; only a delta against a control arm is interpretable
 * (`docs/framework/measurement.md`). This panel shows the raw share because there is no
 * control-arm contrast on this page — the caveat belongs beside it, not omitted.
 */

import { useEffect, useState } from 'react'

import { api } from '../api/client'
import { humanise } from '../lib/format'
import type { Citizen, CitizenResponse, RunRecord } from '../types/artsoc'
import ChatBox, { useChat } from './ChatBox'

const DIMENSIONS = ['region', 'urbanicity', 'age_band', 'sex', 'education', 'party_id'] as const

interface Segment {
  dimension: string
  category: string
}

export default function AudiencePanel({
  sessionId,
  arm,
  record,
}: {
  sessionId: string
  arm: string
  record: RunRecord
}) {
  const [breakdown, setBreakdown] = useState<Record<string, number> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Segment | null>(null)

  useEffect(() => {
    setBreakdown(null)
    setSelected(null)
    void api
      .audienceBreakdown(sessionId, arm)
      .then(setBreakdown)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [sessionId, arm])

  const audience = record.audience
  if (!audience) return null

  const citizens: Citizen[] = audience.citizens ?? []
  const responses: CitizenResponse[] = audience.responses ?? []
  const responseByCitizen = new Map(responses.map((r) => [r.citizen_id, r]))

  const matching = selected
    ? citizens
        .filter((c) => (c as unknown as Record<string, string>)[selected.dimension] === selected.category)
        .slice(0, 4)
    : []

  return (
    <section className="section">
      <header>
        <h2>The audience</h2>
        <p className="subtitle">
          A stratified sample of the public reacting to the decision, after the fact — an
          outcome measure, not an input. Weighted approve share by stratum, pooled across
          every replication of this arm; not a finding on its own, only a delta against a
          control arm would be. Click a category to open a few of this run&rsquo;s actual
          sampled citizens.
        </p>
      </header>

      {error && <p className="notice stop small">{error}</p>}
      {!breakdown && !error && <p className="spin small">Loading…</p>}

      {breakdown && (
        <div className="grid two">
          {DIMENSIONS.map((dim) => (
            <DimensionBars
              key={dim}
              dimension={dim}
              breakdown={breakdown}
              selected={selected}
              onSelect={(category) => setSelected({ dimension: dim, category })}
            />
          ))}
        </div>
      )}

      {selected && (
        <div style={{ marginTop: '1.25rem' }}>
          <h4>
            {humanise(selected.dimension)}: {humanise(selected.category)}
          </h4>
          {matching.length === 0 ? (
            <p className="empty">No sampled citizen in this run matches that category.</p>
          ) : (
            <div className="grid two">
              {matching.map((citizen) => (
                <CitizenCard
                  key={citizen.citizen_id}
                  sessionId={sessionId}
                  arm={arm}
                  runId={record.run_id}
                  citizen={citizen}
                  response={responseByCitizen.get(citizen.citizen_id)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function DimensionBars({
  dimension,
  breakdown,
  selected,
  onSelect,
}: {
  dimension: string
  breakdown: Record<string, number>
  selected: Segment | null
  onSelect: (category: string) => void
}) {
  const prefix = `${dimension}:`
  const rows = Object.entries(breakdown)
    .filter(([key]) => key.startsWith(prefix))
    .map(([key, share]) => ({ category: key.slice(prefix.length), share }))
    .sort((a, b) => a.category.localeCompare(b.category))

  if (rows.length === 0) return null

  const width = 320
  const labelW = 96
  const barW = width - labelW - 44
  const row = 20

  return (
    <div>
      <p className="tiny faint" style={{ margin: '0 0 0.2rem', textTransform: 'uppercase' }}>
        {humanise(dimension)}
      </p>
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${rows.length * row + 4}`}
        width="100%"
        height={rows.length * row + 4}
        role="img"
        aria-label={`Approval by ${dimension}`}
      >
        {rows.map((r, i) => {
          const y = i * row
          const isSelected =
            selected?.dimension === dimension && selected.category === r.category
          const w = Math.max(r.share > 0 ? 1 : 0, r.share * barW)
          return (
            <g
              key={r.category}
              style={{ cursor: 'pointer' }}
              onClick={() => onSelect(r.category)}
            >
              <rect x={0} y={y} width={width} height={row - 2} fill="transparent" />
              <text
                x={labelW - 6}
                y={y + row / 2}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                fill={isSelected ? 'var(--accent)' : 'var(--ink-2)'}
              >
                {humanise(r.category)}
              </text>
              <rect
                className={`bar${isSelected ? ' nuclear' : ''}`}
                x={labelW}
                y={y + 3}
                width={w}
                height={row - 8}
              >
                <title>{`${dimension}: ${r.category} — ${(r.share * 100).toFixed(0)}% approve`}</title>
              </rect>
              <text x={labelW + barW + 6} y={y + row / 2} dy="0.32em" fontSize={9} fill="var(--ink-3)">
                {(r.share * 100).toFixed(0)}%
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function CitizenCard({
  sessionId,
  arm,
  runId,
  citizen,
  response,
}: {
  sessionId: string
  arm: string
  runId: string
  citizen: Citizen
  response: CitizenResponse | undefined
}) {
  const label = `citizen ${citizen.citizen_id}`
  const chat = useChat(
    () => api.chatHistory(sessionId, arm, 'citizen', runId, citizen.citizen_id),
    (message) => api.sendChat(sessionId, arm, 'citizen', runId, citizen.citizen_id, message),
    `${sessionId}:${arm}:${runId}:${citizen.citizen_id}`,
  )

  return (
    <article className="answer">
      <p className="muted small" style={{ margin: 0 }}>
        {humanise(citizen.region)} · {humanise(citizen.urbanicity)} ·{' '}
        {humanise(citizen.age_band)} · {humanise(citizen.sex)} · {humanise(citizen.education)} ·{' '}
        {humanise(citizen.party_id)}
      </p>
      {response ? (
        <>
          <h5>Recorded reaction</h5>
          <p>
            <span className="tag">{humanise(response.approval)}</span>{' '}
            {response.refused ? (
              <span className="faint">declined to answer in character.</span>
            ) : (
              response.rationale
            )}
          </p>
        </>
      ) : (
        <p className="empty">No response recorded for this citizen.</p>
      )}
      <ChatBox
        label={label}
        history={chat.history}
        loading={chat.loading}
        error={chat.error}
        onSend={chat.onSend}
        sending={chat.sending}
      />
    </article>
  )
}
