/**
 * The shapes the API accepts and returns, on top of the generated model types.
 *
 * Everything with a pydantic model behind it is re-exported from the generated file. The
 * only thing declared here is the *request* body, which has no pydantic response model to
 * generate from — and it is declared as a narrowing of `SessionSpec` so it cannot acquire a
 * field the server would reject.
 */

export type {
  ArmInfo,
  CallEstimate,
  ProgressEvent,
  RepresentativeView,
  ScenarioInfo,
  SessionCreated,
  SessionSpec,
  SessionState,
  SessionSummary,
} from './artsoc'

import type { SessionSpec } from './artsoc'

/**
 * What the client sends to start or price a session.
 *
 * `session_id` is omitted deliberately: the server generates it. Everything else is a
 * choice among committed configs — a scenario id, some arm *names*, and how many
 * replications. There is no experimental parameter here and there must never be one: a
 * control that let a viewer construct a configuration no file in `configs/` describes would
 * break invariant 5 by another route and make the results untraceable.
 */
export type SessionSpecRequest = Omit<SessionSpec, 'session_id'>
