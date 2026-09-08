/**
 * The session store: what is running, what has landed, and what it has cost.
 *
 * Context plus `useReducer`, no state library. The state is one running session and a list
 * of finished ones; a store framework would be more machinery than the problem has.
 *
 * The live rung counts here are display state for the running view only. They are counted
 * from the progress stream so a degenerate distribution is visible before the sweep ends —
 * under a live backend that is money not spent. Everything reported afterwards comes from
 * `metrics.summarise` on the server, never from these.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from 'react'

import { api, subscribe } from '../api/client'
import type { ProgressEvent, SessionSpecRequest } from '../types/api'
import type { SessionState } from '../types/artsoc'

interface LiveArm {
  arm: string
  completed: number
  total: number
  /** Terminal rungs seen so far, for the live histogram. Counts, keyed by rung. */
  rungs: Record<number, number>
  failures: string[]
}

interface State {
  sessions: SessionState[]
  loading: boolean
  error: string | null
  /** The session currently streaming, if any. */
  activeId: string | null
  live: Record<string, LiveArm>
  spend: number
  finished: boolean
}

type Action =
  | { type: 'loading' }
  | { type: 'sessions'; sessions: SessionState[] }
  | { type: 'error'; message: string }
  | { type: 'watch'; sessionId: string; arms: string[]; n: number }
  | { type: 'progress'; event: ProgressEvent }
  | { type: 'finished'; state: SessionState }
  | { type: 'clear' }

const initial: State = {
  sessions: [],
  loading: false,
  error: null,
  activeId: null,
  live: {},
  spend: 0,
  finished: false,
}

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case 'loading':
      return { ...state, loading: true, error: null }

    case 'sessions':
      return { ...state, loading: false, sessions: action.sessions }

    case 'error':
      return { ...state, loading: false, error: action.message }

    case 'watch':
      return {
        ...state,
        activeId: action.sessionId,
        finished: false,
        spend: 0,
        error: null,
        live: Object.fromEntries(
          action.arms.map((arm) => [
            arm,
            { arm, completed: 0, total: action.n, rungs: {}, failures: [] },
          ]),
        ),
      }

    case 'progress': {
      const { event } = action
      const existing = state.live[event.arm]
      if (!existing) return state
      const next: LiveArm = {
        ...existing,
        completed: event.completed,
        rungs: { ...existing.rungs },
        failures: event.failure ? [...existing.failures, event.failure] : existing.failures,
      }
      if (event.rung !== null && event.rung !== undefined) {
        next.rungs[event.rung] = (next.rungs[event.rung] ?? 0) + 1
      }
      return {
        ...state,
        live: { ...state.live, [event.arm]: next },
        spend: event.cumulative_cost_usd ?? state.spend,
      }
    }

    case 'finished':
      return {
        ...state,
        finished: true,
        sessions: [
          action.state,
          ...state.sessions.filter((s) => s.spec.session_id !== action.state.spec.session_id),
        ],
      }

    case 'clear':
      return { ...initial, sessions: state.sessions }
  }
}

interface Store extends State {
  refresh: () => Promise<void>
  start: (spec: SessionSpecRequest) => Promise<string>
  cancel: () => Promise<void>
  clear: () => void
}

const SessionContext = createContext<Store | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, initial)

  const refresh = useCallback(async () => {
    dispatch({ type: 'loading' })
    try {
      dispatch({ type: 'sessions', sessions: await api.sessions() })
    } catch (error) {
      dispatch({ type: 'error', message: (error as Error).message })
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const start = useCallback(async (spec: SessionSpecRequest) => {
    const created = await api.create(spec)
    dispatch({
      type: 'watch',
      sessionId: created.session_id,
      arms: spec.arms,
      n: spec.n,
    })
    return created.session_id
  }, [])

  // Subscribing here rather than in the running view means a viewer can navigate away from
  // the progress screen without silently dropping the stream and the spend counter with it.
  useEffect(() => {
    if (!state.activeId || state.finished) return
    return subscribe(state.activeId, {
      progress: (event) => dispatch({ type: 'progress', event }),
      done: (session) => dispatch({ type: 'finished', state: session }),
    })
  }, [state.activeId, state.finished])

  const cancel = useCallback(async () => {
    if (!state.activeId) return
    try {
      await api.cancel(state.activeId)
    } catch (error) {
      dispatch({ type: 'error', message: (error as Error).message })
    }
  }, [state.activeId])

  const value = useMemo<Store>(
    () => ({ ...state, refresh, start, cancel, clear: () => dispatch({ type: 'clear' }) }),
    [state, refresh, start, cancel],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSessions(): Store {
  const store = useContext(SessionContext)
  if (!store) throw new Error('useSessions must be used inside a SessionProvider')
  return store
}
