export type TaskTiming = {
  startedAt?: number
  finishedAt?: number
}

/** Elapsed milliseconds for a task timing window. Returns undefined when start is unknown. */
export function taskDurationMs(timing: TaskTiming, now: number = Date.now()): number | undefined {
  const startedAt = timing.startedAt
  if (typeof startedAt !== 'number' || !Number.isFinite(startedAt)) return undefined
  const end = typeof timing.finishedAt === 'number' && Number.isFinite(timing.finishedAt)
    ? timing.finishedAt
    : now
  return Math.max(0, Math.round(end - startedAt))
}

/** Human-readable duration for task rows. Unknown timing renders as an em dash. */
export function formatTaskDuration(ms?: number): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const rem = Math.round(seconds % 60)
  if (minutes < 60) return rem > 0 ? `${minutes}m ${rem}s` : `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remMin = minutes % 60
  return remMin > 0 ? `${hours}h ${remMin}m` : `${hours}h`
}
