/**
 * The playback cursor over a run's loop steps.
 *
 * **One cursor, three panels.** The Gantt, the interaction graph and the event log all read
 * this and none of them keeps its own position. Separate state would let them drift apart on
 * screen, and the whole point of showing them together is that they are three views of one
 * sequence.
 *
 * The cursor indexes *loop steps*, not time. `views.loop_steps` derives them from record
 * structure, so they are deterministic and reproducible from config plus seed. Nothing in
 * `RunRecord` carries a timestamp, and nothing should: per-call timing would mean persisting
 * the call log, which holds every system and user prompt.
 */

import { useCallback, useEffect, useState } from 'react'

/**
 * Seconds spent on each loop step, slowest last.
 *
 * Expressed as seconds per step rather than as a multiplier, because the question a viewer
 * is actually asking is "how long do I get to read this one" — and a theorist's position
 * plus its reasoning is a paragraph, not a label. A multiplier makes that a division.
 */
export const STEP_SECONDS = [0.5, 1, 2, 4, 8, 20] as const
export type StepSeconds = (typeof STEP_SECONDS)[number]

/** One step per second. Slow enough to follow a decline and see who was asked next. */
export const DEFAULT_STEP_SECONDS: StepSeconds = 1

export interface Playback {
  /** Steps with index <= cursor have happened. -1 means nothing has happened yet. */
  cursor: number
  total: number
  playing: boolean
  stepSeconds: StepSeconds
  atEnd: boolean
  play: () => void
  pause: () => void
  toggle: () => void
  step: (delta: number) => void
  seek: (index: number) => void
  restart: () => void
  showAll: () => void
  setStepSeconds: (seconds: StepSeconds) => void
}

export function usePlayback(total: number): Playback {
  // Starts complete rather than empty. A viewer who opens a run detail should see the run,
  // and press play to watch it assemble — not face a blank canvas and have to work out why.
  const [cursor, setCursor] = useState(total - 1)
  const [playing, setPlaying] = useState(false)
  const [stepSeconds, setStepSeconds] = useState<StepSeconds>(DEFAULT_STEP_SECONDS)

  useEffect(() => {
    setCursor(total - 1)
    setPlaying(false)
  }, [total])

  useEffect(() => {
    if (!playing || total === 0) return
    const interval = window.setInterval(
      () =>
        setCursor((current) => {
          if (current >= total - 1) {
            setPlaying(false)
            return current
          }
          return current + 1
        }),
      stepSeconds * 1000,
    )
    return () => window.clearInterval(interval)
  }, [playing, stepSeconds, total])

  const clamp = useCallback(
    (index: number) => Math.max(-1, Math.min(total - 1, index)),
    [total],
  )

  const play = useCallback(() => {
    // Playing from the end would look like a broken control, so it rewinds first.
    setCursor((current) => (current >= total - 1 ? -1 : current))
    setPlaying(true)
  }, [total])

  return {
    cursor,
    total,
    playing,
    stepSeconds,
    atEnd: cursor >= total - 1,
    play,
    pause: () => setPlaying(false),
    toggle: () => (playing ? setPlaying(false) : play()),
    step: (delta: number) => {
      setPlaying(false)
      setCursor((current) => clamp(current + delta))
    },
    seek: (index: number) => {
      setPlaying(false)
      setCursor(clamp(index))
    },
    restart: () => {
      setPlaying(false)
      setCursor(-1)
    },
    showAll: () => {
      setPlaying(false)
      setCursor(total - 1)
    },
    setStepSeconds,
  }
}
