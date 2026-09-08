import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import RunDetail from './views/RunDetail'
import SessionCreate from './views/SessionCreate'
import SessionList from './views/SessionList'
import SessionResults from './views/SessionResults'
import SessionRunning from './views/SessionRunning'

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">artsoc</span>
        <span className="tag">
          persona panel &rarr; advisory brief &rarr; one presidential decision, under Monte
          Carlo
        </span>
        <nav>
          <NavLink to="/new" className={({ isActive }) => (isActive ? 'active' : '')}>
            New session
          </NavLink>
          <NavLink to="/sessions" className={({ isActive }) => (isActive ? 'active' : '')}>
            Sessions
          </NavLink>
        </nav>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/sessions" replace />} />
          <Route path="/new" element={<SessionCreate />} />
          <Route path="/sessions" element={<SessionList />} />
          <Route path="/sessions/:sessionId/running" element={<SessionRunning />} />
          <Route path="/sessions/:sessionId" element={<SessionResults />} />
          <Route path="/sessions/:sessionId/runs/:arm" element={<RunDetail />} />
          <Route path="*" element={<Navigate to="/sessions" replace />} />
        </Routes>
      </main>
    </div>
  )
}
