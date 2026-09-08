/**
 * The one cursor the Gantt, the graph and the event log all read.
 *
 * **It sticks to the top of the viewport while playing.** The three panels it drives are
 * taller than a screen, so playback is watched from wherever the interesting panel is —
 * and controls that scroll away leave no way to pause what you are reading.
 *
 * Speed is seconds per step, not a multiplier. The question a viewer is asking is "how long
 * do I get to read this one", and a theorist's position plus its reasoning is a paragraph.
 * The step counter says "loop step" rather than a time, because that is what the index is:
 * a position in a deterministic sequence derived from record structure, not a clock.
 */

import { STEP_SECONDS, type Playback, type StepSeconds } from '../lib/playback'

export default function PlaybackControls({ playback }: { playback: Playback }) {
  const { cursor, total, playing, stepSeconds } = playback

  return (
    <div className="playback">
      <div className="row">
        <button className="small" onClick={playback.restart} title="Back to the start">
          ⏮
        </button>
        <button className="small" onClick={() => playback.step(-1)} disabled={cursor < 0}>
          ◀ step
        </button>
        <button className="primary small" onClick={playback.toggle} disabled={total === 0}>
          {playing ? '❚❚ pause' : '▶ play'}
        </button>
        <button
          className="small"
          onClick={() => playback.step(1)}
          disabled={cursor >= total - 1}
        >
          step ▶
        </button>
        <button className="small" onClick={playback.showAll} title="Reveal the whole run">
          ⏭
        </button>

        <input
          type="range"
          min={-1}
          max={Math.max(0, total - 1)}
          value={cursor}
          onChange={(e) => playback.seek(Number(e.target.value))}
          style={{ flex: 1, minWidth: '140px' }}
          aria-label="Loop step"
        />

        <span className="mono small muted" style={{ minWidth: '11ch' }}>
          step {cursor < 0 ? '—' : cursor} / {Math.max(0, total - 1)}
        </span>

        <label htmlFor="pace" className="small faint" style={{ margin: 0 }}>
          pace
        </label>
        <select
          id="pace"
          value={stepSeconds}
          onChange={(e) => playback.setStepSeconds(Number(e.target.value) as StepSeconds)}
          style={{ width: 'auto' }}
          aria-label="Seconds per loop step"
        >
          {STEP_SECONDS.map((seconds) => (
            <option key={seconds} value={seconds}>
              {seconds}s / step
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
