/**
 * A session in flight: progress per arm, spend as it accrues, and the distribution forming.
 *
 * The live histogram is worth the space. A distribution that is obviously degenerate — every
 * replication landing on one rung — is worth killing before the sweep finishes, and under a
 * live backend that is money not spent.
 *
 * It is display state only. Everything reported afterwards comes from `metrics.summarise` on
 * the server; nothing on this page is counted twice or read as a result.
 */

import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import RungHistogram from '../components/RungHistogram'
import { useSessions } from '../context/SessionContext'
import { usd } from '../lib/format'

export default function SessionRunning() {
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const { live, spend, finished, activeId, cancel, sessions } = useSessions()

  const arms = Object.values(live)
  const total = arms.reduce((sum, arm) => sum + arm.total, 0)
  const completed = arms.reduce((sum, arm) => sum + arm.completed, 0)
  const failures = arms.flatMap((arm) => arm.failures)

  useEffect(() => {
    if (finished) {
      const timer = window.setTimeout(() => navigate(`/sessions/${sessionId}`), 900)
      return () => window.clearTimeout(timer)
    }
  }, [finished, navigate, sessionId])

  // Reloading this URL loses the stream: the subscription belongs to the session that was
  // started in this tab. Say so rather than showing an empty progress bar forever.
  if (activeId !== sessionId) {
    const known = sessions.find((s) => s.spec.session_id === sessionId)
    return (
      <section className="section">
        <h2>Not streaming this session</h2>
        <p className="muted">
          Progress is streamed to the tab that started the session. This one is not
          subscribed{known ? `, and the session is ${known.status}` : ''}.
        </p>
        <Link to={`/sessions/${sessionId}`}>
          <button className="primary">Open results</button>
        </Link>
      </section>
    )
  }

  return (
    <>
      <div className="row">
        <h1 style={{ margin: 0 }}>{finished ? 'Session complete' : 'Running'}</h1>
        <div className="spacer" />
        <span className="muted">
          {completed} / {total} replications
        </span>
        <span className="muted">
          spend {usd(spend)}
          {completed > 0 && !finished && (
            <span className="faint"> · projected {usd((spend / completed) * total)}</span>
          )}
        </span>
        {!finished && (
          <button className="danger small" onClick={() => void cancel()}>
            Cancel
          </button>
        )}
      </div>

      <p className="faint small" style={{ maxWidth: '80ch' }}>
        Spend is metered from what each replication actually billed, not from a pre-run
        estimate. Cancelling keeps every replication already completed — they are still data,
        provided the count stays visible.
      </p>

      {failures.length > 0 && (
        <div className="notice warn">
          <strong>{failures.length} replication(s) failed</strong>
          They are excluded from the output and listed here rather than dropped silently: a
          replication may fail for reasons correlated with its outcome, so a distribution over
          the survivors would be biased with nothing to show it.
          <ul className="small" style={{ margin: '0.4rem 0 0' }}>
            {failures.slice(0, 5).map((failure) => (
              <li key={failure}>{failure}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid two">
        {arms.map((arm) => {
          const seen = Object.values(arm.rungs).reduce((a, b) => a + b, 0)
          return (
            <section className="section" key={arm.arm}>
              <header>
                <div className="row">
                  <h2 style={{ margin: 0 }}>{arm.arm}</h2>
                  <div className="spacer" />
                  <span className="mono small muted">
                    {arm.completed} / {arm.total}
                  </span>
                </div>
                <div className="progress-track" style={{ marginTop: '0.5rem' }}>
                  <div
                    className="progress-fill"
                    style={{ width: `${arm.total ? (arm.completed / arm.total) * 100 : 0}%` }}
                  />
                </div>
              </header>

              {seen > 0 ? (
                <RungHistogram
                  distribution={Object.fromEntries(
                    Object.entries(arm.rungs).map(([k, v]) => [k, v]),
                  )}
                  n={seen}
                  height={150}
                />
              ) : (
                <p className="empty">waiting for the first replication</p>
              )}
            </section>
          )
        })}
      </div>

      {finished && (
        <Link to={`/sessions/${sessionId}`}>
          <button className="primary">Open results</button>
        </Link>
      )}
    </>
  )
}
