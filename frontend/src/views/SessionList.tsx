/** Sessions on disk, newest first. */

import { Link } from 'react-router-dom'

import { useSessions } from '../context/SessionContext'
import { elapsed } from '../lib/format'

export default function SessionList() {
  const { sessions, loading, error, refresh } = useSessions()

  return (
    <>
      <div className="row">
        <h1 style={{ margin: 0 }}>Sessions</h1>
        <div className="spacer" />
        <button className="small" onClick={() => void refresh()} disabled={loading}>
          Refresh
        </button>
        <Link to="/new">
          <button className="primary small">New session</button>
        </Link>
      </div>

      {error && (
        <div className="banner danger" style={{ marginTop: '1rem' }}>
          <strong>COULD NOT LIST SESSIONS</strong>
          {error}
        </div>
      )}

      <section className="panel" style={{ marginTop: '1rem' }}>
        {sessions.length === 0 ? (
          <p className="empty">
            No sessions yet. Start one, or run <code>make demo-fixture</code> for a free
            mock-backed session to look at.
          </p>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>label</th>
                  <th>arms</th>
                  <th className="num">n</th>
                  <th>status</th>
                  <th className="num">spend</th>
                  <th className="num">took</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.map((session) => {
                  const done = session.progress?.every((p) => p.completed > 0) ?? false
                  return (
                    <tr key={session.spec.session_id}>
                      <td>
                        {session.spec.label || (
                          <span className="faint mono">
                            {(session.spec.session_id ?? '').slice(0, 8)}
                          </span>
                        )}
                      </td>
                      <td className="small faint">{session.spec.arms.join(', ')}</td>
                      <td className="num">{session.spec.n}</td>
                      <td>{session.status}</td>
                      <td className="num">${(session.est_cost_usd ?? 0).toFixed(4)}</td>
                      <td className="num faint">
                        {session.created_at
                          ? elapsed(session.created_at, session.finished_at)
                          : '—'}
                      </td>
                      <td>
                        {done ? (
                          <Link to={`/sessions/${session.spec.session_id}`}>results</Link>
                        ) : (
                          <span className="faint">no records</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
