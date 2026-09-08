/**
 * Fetch wrappers and the progress subscription.
 *
 * Everything here is a transport concern. There are no derivations in this file and there
 * should never be: what the UI renders is computed in `src/artsoc/views.py`, where the
 * Python test suite can reach it. A statistic computed in the browser is a statistic
 * nothing tests.
 */

import type {
  ArmInfo,
  CallEstimate,
  ProgressEvent,
  RepresentativeView,
  ScenarioInfo,
  SessionCreated,
  SessionSpecRequest,
} from '../types/api'
import type { SessionState, SessionSummary } from '../types/artsoc'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
  }
}

/** Raised when a session was posted without `confirm`. Carries the call estimate. */
export class ConfirmationRequired extends ApiError {
  constructor(
    readonly estimate: CallEstimate,
    message: string,
  ) {
    super(409, message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (response.ok) return (await response.json()) as T

  let detail: unknown
  try {
    detail = (await response.json()).detail
  } catch {
    detail = await response.text()
  }

  // The cost gate is a 409 carrying the estimate rather than an error string, because the
  // UI has to render the estimate and ask before anything is spent.
  if (response.status === 409 && isConfirmation(detail)) {
    throw new ConfirmationRequired(detail.estimate, detail.message)
  }
  throw new ApiError(response.status, describe(detail) ?? response.statusText, detail)
}

function isConfirmation(
  detail: unknown,
): detail is { reason: string; message: string; estimate: CallEstimate } {
  return (
    typeof detail === 'object' &&
    detail !== null &&
    (detail as { reason?: string }).reason === 'confirmation required'
  )
}

function describe(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join('; ')
  }
  return detail === undefined ? undefined : JSON.stringify(detail)
}

export const api = {
  scenarios: () => request<ScenarioInfo[]>('/api/scenarios'),

  arms: (scenarioId?: string) =>
    request<ArmInfo[]>(
      scenarioId ? `/api/arms?scenario_id=${encodeURIComponent(scenarioId)}` : '/api/arms',
    ),

  sessions: () => request<SessionState[]>('/api/sessions'),

  session: (id: string) => request<SessionState>(`/api/sessions/${id}`),

  summary: (id: string) => request<SessionSummary>(`/api/sessions/${id}/summary`),

  /**
   * Ask what a session would cost without starting it. The server refuses an unconfirmed
   * POST with the estimate attached, so the estimate and the thing being confirmed can
   * never describe different runs.
   */
  estimate: async (spec: SessionSpecRequest): Promise<CallEstimate> => {
    try {
      await request<SessionCreated>('/api/sessions', {
        method: 'POST',
        body: JSON.stringify(spec),
      })
    } catch (error) {
      if (error instanceof ConfirmationRequired) return error.estimate
      throw error
    }
    throw new Error('the server started a session that was never confirmed')
  },

  create: (spec: SessionSpecRequest) =>
    request<SessionCreated>('/api/sessions?confirm=true', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),

  cancel: (id: string) =>
    request<SessionState>(`/api/sessions/${id}/cancel`, { method: 'POST' }),

  representative: (id: string, arm: string, revealGroundTruth = false) =>
    request<RepresentativeView>(
      `/api/sessions/${id}/runs/${encodeURIComponent(arm)}/representative` +
        (revealGroundTruth ? '?reveal_ground_truth=true' : ''),
    ),
}

/**
 * Subscribe to a running session's progress.
 *
 * One event per completed replication. Worth streaming rather than polling: a distribution
 * that is obviously degenerate is worth killing early, and under a live backend that is
 * money not spent.
 *
 * Returns an unsubscribe function.
 */
export function subscribe(
  sessionId: string,
  handlers: { progress?: (event: ProgressEvent) => void; done?: (state: SessionState) => void },
): () => void {
  const source = new EventSource(`/api/sessions/${sessionId}/events`)

  source.addEventListener('progress', (event) => {
    handlers.progress?.(JSON.parse((event as MessageEvent<string>).data) as ProgressEvent)
  })
  source.addEventListener('done', (event) => {
    handlers.done?.(JSON.parse((event as MessageEvent<string>).data) as SessionState)
    source.close()
  })
  // EventSource retries on its own by default, which would reopen a stream for a session
  // that has finished. Once the server has closed it there is nothing left to receive.
  source.addEventListener('error', () => source.close())

  return () => source.close()
}
