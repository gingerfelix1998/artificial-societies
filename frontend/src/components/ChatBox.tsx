/**
 * A live, on-demand follow-up conversation with one ExComm member or one citizen
 * (ADR 0010) — triggered from the viewer after the run has already finished.
 *
 * **This is not the recorded run.** Nothing typed here, and nothing said back, re-enters
 * `RunRecord` or changes any figure on the page: it is a side conversation for exploring
 * reasoning, billed per message, the same accounting `narrative`/`analysis/ask` already
 * get. The identity behind the reply is exactly the anonymous one the recorded turn used —
 * a real name shown beside this box, where one is shown, is a label this component
 * attaches for display; it was never told to the model.
 */

import { useEffect, useState } from 'react'

import { ApiError } from '../api/client'
import type { ChatTurn } from '../types/artsoc'

interface Props {
  /** Who is being talked to, for the placeholder and the empty state. */
  label: string
  history: ChatTurn[]
  loading: boolean
  error: string | null
  onSend: (message: string) => void
  sending: boolean
}

export default function ChatBox({ label, history, loading, error, onSend, sending }: Props) {
  const [draft, setDraft] = useState('')

  const submit = () => {
    const message = draft.trim()
    if (!message || sending) return
    onSend(message)
    setDraft('')
  }

  return (
    <div className="chat">
      <div className="chat-history">
        {loading ? (
          <p className="spin small">Loading…</p>
        ) : history.length === 0 ? (
          <p className="empty small">
            Nothing sent yet. Ask {label} a follow-up about their reasoning.
          </p>
        ) : (
          history.map((turn, i) => (
            <p key={i} className={`chat-turn ${turn.role}`}>
              <span className="tag plain tiny">{turn.role === 'user' ? 'you' : label}</span>
              {turn.text}
            </p>
          ))
        )}
      </div>
      {error && <p className="notice stop small">{error}</p>}
      <div className="row tight">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={`Ask ${label} something…`}
          disabled={sending}
          rows={2}
          style={{ flex: 1 }}
        />
        <button className="small" onClick={submit} disabled={sending || !draft.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}

/** Shared send-and-refresh logic for a chat, so the ExComm panel and the citizen segment
 *  panel do not each reimplement history-fetching, error handling and the pending state. */
export function useChat(
  fetchHistory: () => Promise<ChatTurn[]>,
  send: (message: string) => Promise<ChatTurn>,
  key: string,
) {
  const [history, setHistory] = useState<ChatTurn[]>([])
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    void fetchHistory()
      .then(setHistory)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
    // `key` identifies who the conversation is with; a new one means a fresh fetch.
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps

  const onSend = (message: string) => {
    setSending(true)
    setError(null)
    void send(message)
      .then((turn) => setHistory((h) => [...h, { role: 'user', text: message, ts: '' }, turn]))
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e)),
      )
      .finally(() => setSending(false))
  }

  return { history, loading, sending, error, onSend }
}
