import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import MacroAnalysis from './views/MacroAnalysis'
import RepresentativeRun from './views/RepresentativeRun'
import SessionCreate from './views/SessionCreate'
import SessionList from './views/SessionList'
import SessionRunning from './views/SessionRunning'
import SimulationLanding from './views/SimulationLanding'

export default function App() {
  // The run page carries a graph, a timeline and a log side by side, so it gets the wider
  // measure. Everything else is read as a document and keeps the narrower one.
  const wide = useLocation().pathname.includes('/run/')

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">artsoc</span>
        <span className="tag plain">
          a panel of nuclear strategists, one presidential decision, under Monte Carlo
        </span>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Simulations
          </NavLink>
          <NavLink to="/new" className={({ isActive }) => (isActive ? 'active' : '')}>
            New
          </NavLink>
        </nav>
      </header>

      <main className={wide ? 'wide' : undefined}>
        <Routes>
          <Route path="/" element={<SessionList />} />
          <Route path="/new" element={<SessionCreate />} />
          <Route path="/sessions/:sessionId" element={<SimulationLanding />} />
          <Route path="/sessions/:sessionId/macro" element={<MacroAnalysis />} />
          <Route path="/sessions/:sessionId/running" element={<SessionRunning />} />
          <Route path="/sessions/:sessionId/run/:arm" element={<RepresentativeRun />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
