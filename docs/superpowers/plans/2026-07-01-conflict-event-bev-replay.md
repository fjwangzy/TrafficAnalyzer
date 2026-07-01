# Conflict Event BEV Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators click a motor/non-motor conflict event in the Monitoring page and replay that event on the BEV map with risk context and playback controls.

**Architecture:** Keep Kafka/WebSocket contracts unchanged. Add focused frontend helpers that resolve conflict events to local trajectory snapshots, then pass a compact `conflictReplay` object from `Monitoring` to `BevMap`. `BevMap` renders a fourth OpenLayers vector layer above historical/completed/active trajectories and drives replay with `requestAnimationFrame`.

**Tech Stack:** React + TypeScript, Vite/Vitest, OpenLayers, existing shadcn/ui-style local components, existing `bev-trajectory-utils.ts` coordinate helpers.

---

## File Structure

- Create: `traffic-fly-console/src/features/monitoring/conflict-replay-utils.ts`
  - Owns pure data types and helpers for resolving conflict events, extracting world points, slicing replay windows, and computing conflict fallback points.
- Create: `traffic-fly-console/src/features/monitoring/conflict-replay-utils.test.ts`
  - Covers trajectory lookup, fallback behavior, replay window slicing, and degraded states.
- Modify: `traffic-fly-console/src/features/monitoring/index.tsx`
  - Owns selected event state, playback controls, event list click behavior, and `conflictReplay` prop construction.
- Modify: `traffic-fly-console/src/features/monitoring/bev-map.tsx`
  - Adds `conflictReplay` prop, OpenLayers replay layer, animation loop, risk drawing, dimming behavior, and in-map control/status overlay.
- Modify: `docs/TASKS.md`
  - Records the completed monitoring replay work after verification.

## Task 1: Conflict Replay Helpers

**Files:**
- Create: `traffic-fly-console/src/features/monitoring/conflict-replay-utils.ts`
- Create: `traffic-fly-console/src/features/monitoring/conflict-replay-utils.test.ts`

- [ ] **Step 1: Write failing tests for lookup, fallback, and slicing**

Create `traffic-fly-console/src/features/monitoring/conflict-replay-utils.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  buildConflictReplayTracks,
  sliceReplayPoints,
  type ConflictReplayEvent,
} from './conflict-replay-utils'
import type { TrajectoryPoint } from './bev-trajectory-utils'

const event: ConflictReplayEvent = {
  motor_id: 101,
  non_motor_id: 202,
  motor_position_m: [10, 20],
  non_motor_position_m: [13, 24],
  distance_m: 5,
  ttc_sec: 1.2,
  severity: 'warning',
  world_anchor_lat_lon: [36.7, 117.02],
}

const motorTrack: TrajectoryPoint = {
  track_id: 101,
  vehicle_class: 'motor',
  timestamp_first: 10,
  timestamp_last: 15,
  world_anchor_lat_lon: [36.7, 117.02],
  trajectory_world_m: [[0, 0], [5, 10], [10, 20]],
}

const nonMotorTrack: TrajectoryPoint = {
  track_id: 202,
  vehicle_class: 'non_motor',
  timestamp_first: 11,
  timestamp_last: 15,
  world_anchor_lat_lon: [36.7, 117.02],
  trajectory_world_m: [[20, 20], [16, 22], [13, 24]],
}

describe('buildConflictReplayTracks', () => {
  it('resolves motor and non-motor tracks from session trajectories first', () => {
    const replay = buildConflictReplayTracks({
      event,
      sessionActiveTrajectories: [motorTrack, nonMotorTrack],
      activeTrajectories: [],
      completedTrajectories: [],
      windowSec: 6,
    })

    expect(replay.motor.points).toEqual([[0, 0], [5, 10], [10, 20]])
    expect(replay.nonMotor.points).toEqual([[20, 20], [16, 22], [13, 24]])
    expect(replay.status).toBe('ready')
    expect(replay.hasInsufficientTrajectory).toBe(false)
  })

  it('uses conflict positions as single-point fallbacks when tracks are missing', () => {
    const replay = buildConflictReplayTracks({
      event,
      sessionActiveTrajectories: [],
      activeTrajectories: [],
      completedTrajectories: [],
      windowSec: 6,
    })

    expect(replay.motor.points).toEqual([[10, 20]])
    expect(replay.nonMotor.points).toEqual([[13, 24]])
    expect(replay.status).toBe('insufficient')
    expect(replay.hasInsufficientTrajectory).toBe(true)
  })

  it('prefers active tracks over completed tracks when session tracks are absent', () => {
    const replay = buildConflictReplayTracks({
      event,
      sessionActiveTrajectories: [],
      activeTrajectories: [motorTrack],
      completedTrajectories: [nonMotorTrack],
      windowSec: 6,
    })

    expect(replay.motor.source).toBe('active')
    expect(replay.nonMotor.source).toBe('completed')
  })

  it('reports missing world coordinates without throwing', () => {
    const replay = buildConflictReplayTracks({
      event: { motor_id: 101, non_motor_id: 202, severity: 'critical' },
      sessionActiveTrajectories: [{ track_id: 101, trajectory_px: [[1, 2], [2, 3]] }],
      activeTrajectories: [],
      completedTrajectories: [],
      windowSec: 6,
    })

    expect(replay.status).toBe('missing_world')
    expect(replay.hasWorldCoordinates).toBe(false)
  })
})

describe('sliceReplayPoints', () => {
  it('returns a stable prefix based on progress', () => {
    const points = [[0, 0], [1, 1], [2, 2], [3, 3]]
    expect(sliceReplayPoints(points, 0)).toEqual([[0, 0]])
    expect(sliceReplayPoints(points, 0.5)).toEqual([[0, 0], [1, 1], [2, 2]])
    expect(sliceReplayPoints(points, 1)).toEqual(points)
  })
})
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```bash
cd traffic-fly-console
npm test -- conflict-replay-utils.test.ts
```

Expected: FAIL because `conflict-replay-utils.ts` does not exist.

- [ ] **Step 3: Implement the helper module**

Create `traffic-fly-console/src/features/monitoring/conflict-replay-utils.ts`:

```ts
import type { TrajectoryPoint } from './bev-trajectory-utils'

export type ReplayWindowSec = 3 | 6 | 10
export type PlaybackSpeed = 0.5 | 1 | 2
export type PlaybackState = 'playing' | 'paused' | 'ended'
export type ConflictReplayStatus = 'ready' | 'insufficient' | 'missing_world'
export type ConflictReplaySource = 'session' | 'active' | 'completed' | 'event'

export type ConflictReplayEvent = Record<string, unknown> & {
  motor_id?: number | string
  non_motor_id?: number | string
  motor_position_m?: number[]
  non_motor_position_m?: number[]
  distance_m?: number
  ttc_sec?: number
  severity?: string
  world_anchor_lat_lon?: number[]
  received_at?: number
}

export interface ConflictReplayTrack {
  id: string
  role: 'motor' | 'non_motor'
  points: number[][]
  source: ConflictReplaySource
  anchor?: number[]
  vehicleClass?: string | null
}

export interface ConflictReplayTracks {
  event: ConflictReplayEvent
  motor: ConflictReplayTrack
  nonMotor: ConflictReplayTrack
  status: ConflictReplayStatus
  hasInsufficientTrajectory: boolean
  hasWorldCoordinates: boolean
  windowSec: ReplayWindowSec
}

export interface BuildConflictReplayTracksArgs {
  event: ConflictReplayEvent
  sessionActiveTrajectories: TrajectoryPoint[]
  activeTrajectories: TrajectoryPoint[]
  completedTrajectories: TrajectoryPoint[]
  windowSec: ReplayWindowSec
}

const toId = (value: unknown) => value == null ? '' : String(value)

const isWorldPoint = (point: unknown): point is number[] => (
  Array.isArray(point)
  && point.length >= 2
  && Number.isFinite(Number(point[0]))
  && Number.isFinite(Number(point[1]))
)

const normalizePoint = (point: number[]): number[] => [Number(point[0]), Number(point[1])]

const normalizePoints = (points: unknown): number[][] => {
  if (!Array.isArray(points)) return []
  return points.filter(isWorldPoint).map(normalizePoint)
}

function findTrajectoryByTrackId(
  id: unknown,
  sources: Array<{ source: Exclude<ConflictReplaySource, 'event'>; trajectories: TrajectoryPoint[] }>
) {
  const target = toId(id)
  if (!target) return null
  for (const group of sources) {
    const trajectory = group.trajectories.find((traj) => toId(traj.track_id) === target)
    if (trajectory) return { trajectory, source: group.source }
  }
  return null
}

function eventFallbackPoint(event: ConflictReplayEvent, role: 'motor' | 'non_motor') {
  const raw = role === 'motor' ? event.motor_position_m : event.non_motor_position_m
  return isWorldPoint(raw) ? [normalizePoint(raw)] : []
}

function buildTrack(
  event: ConflictReplayEvent,
  role: 'motor' | 'non_motor',
  sources: Array<{ source: Exclude<ConflictReplaySource, 'event'>; trajectories: TrajectoryPoint[] }>
): ConflictReplayTrack {
  const id = role === 'motor' ? event.motor_id : event.non_motor_id
  const found = findTrajectoryByTrackId(id, sources)
  const points = found ? normalizePoints(found.trajectory.trajectory_world_m) : []
  if (points.length > 0 && found) {
    return {
      id: toId(id),
      role,
      points,
      source: found.source,
      anchor: found.trajectory.world_anchor_lat_lon ?? event.world_anchor_lat_lon,
      vehicleClass: found.trajectory.vehicle_class,
    }
  }

  return {
    id: toId(id),
    role,
    points: eventFallbackPoint(event, role),
    source: 'event',
    anchor: event.world_anchor_lat_lon,
    vehicleClass: role === 'motor' ? 'motor' : 'non_motor',
  }
}

function trimToWindow(points: number[][], windowSec: ReplayWindowSec) {
  if (points.length <= 1) return points
  const maxPoints = Math.max(2, Math.round(windowSec * 2))
  return points.slice(Math.max(0, points.length - maxPoints))
}

export function buildConflictReplayTracks({
  event,
  sessionActiveTrajectories,
  activeTrajectories,
  completedTrajectories,
  windowSec,
}: BuildConflictReplayTracksArgs): ConflictReplayTracks {
  const sources = [
    { source: 'session' as const, trajectories: sessionActiveTrajectories },
    { source: 'active' as const, trajectories: activeTrajectories },
    { source: 'completed' as const, trajectories: completedTrajectories },
  ]
  const motor = buildTrack(event, 'motor', sources)
  const nonMotor = buildTrack(event, 'non_motor', sources)
  const trimmedMotor = { ...motor, points: trimToWindow(motor.points, windowSec) }
  const trimmedNonMotor = { ...nonMotor, points: trimToWindow(nonMotor.points, windowSec) }
  const hasWorldCoordinates = trimmedMotor.points.length > 0 || trimmedNonMotor.points.length > 0
  const hasInsufficientTrajectory = trimmedMotor.points.length < 2 || trimmedNonMotor.points.length < 2

  return {
    event,
    motor: trimmedMotor,
    nonMotor: trimmedNonMotor,
    status: !hasWorldCoordinates ? 'missing_world' : hasInsufficientTrajectory ? 'insufficient' : 'ready',
    hasInsufficientTrajectory,
    hasWorldCoordinates,
    windowSec,
  }
}

export function sliceReplayPoints(points: number[][], progress: number): number[][] {
  if (points.length <= 1) return points
  const clamped = Math.max(0, Math.min(1, progress))
  const count = Math.max(1, Math.ceil(clamped * (points.length - 1)) + 1)
  return points.slice(0, count)
}
```

- [ ] **Step 4: Run helper tests and fix only compile/test failures in these helpers**

Run:

```bash
cd traffic-fly-console
npm test -- conflict-replay-utils.test.ts
```

Expected: PASS.

## Task 2: Monitoring State And Clickable Event List

**Files:**
- Modify: `traffic-fly-console/src/features/monitoring/index.tsx`
- Test: manual behavior plus TypeScript build in Task 5

- [ ] **Step 1: Import replay helpers and define playback defaults**

Add imports near the existing BEV imports:

```ts
import {
  buildConflictReplayTracks,
  type ConflictReplayEvent,
  type PlaybackSpeed,
  type PlaybackState,
  type ReplayWindowSec,
} from './conflict-replay-utils'
```

Replace the local `ConflictEvent` type with:

```ts
type ConflictEvent = ConflictReplayEvent
```

Add constants above `Monitoring`:

```ts
const DEFAULT_REPLAY_WINDOW_SEC: ReplayWindowSec = 6
const DEFAULT_PLAYBACK_SPEED: PlaybackSpeed = 1
```

- [ ] **Step 2: Add selected event and playback state**

Inside `Monitoring`, next to `conflictEvents` state, add:

```ts
const [selectedConflictKey, setSelectedConflictKey] = useState<string | null>(null)
const [replayWindowSec, setReplayWindowSec] = useState<ReplayWindowSec>(DEFAULT_REPLAY_WINDOW_SEC)
const [playbackState, setPlaybackState] = useState<PlaybackState>('ended')
const [playbackSpeed, setPlaybackSpeed] = useState<PlaybackSpeed>(DEFAULT_PLAYBACK_SPEED)
const [replayNonce, setReplayNonce] = useState(0)
```

Add a key helper near `formatConflictTime`:

```ts
const conflictEventKey = (event: ConflictEvent, index = 0) => [
  String(event.motor_id ?? 'm'),
  String(event.non_motor_id ?? 'n'),
  String(event.timestamp ?? event.received_at ?? index),
].join(':')
```

- [ ] **Step 3: Reset replay state when switching intersection**

In the `Select` `onValueChange` handler, after `setConflictEvents([])`, add:

```ts
setSelectedConflictKey(null)
setPlaybackState('ended')
setReplayNonce((prev) => prev + 1)
```

- [ ] **Step 4: Build the selected replay object**

Before `return`, add:

```ts
const selectedConflictIndex = conflictEvents.findIndex(
  (event, index) => conflictEventKey(event, index) === selectedConflictKey
)
const selectedConflictEvent = selectedConflictIndex >= 0 ? conflictEvents[selectedConflictIndex] : null
const conflictReplay = selectedConflictEvent
  ? {
      tracks: buildConflictReplayTracks({
        event: selectedConflictEvent,
        sessionActiveTrajectories,
        activeTrajectories,
        completedTrajectories,
        windowSec: replayWindowSec,
      }),
      playbackState,
      playbackSpeed,
      replayNonce,
      onPlaybackStateChange: setPlaybackState,
    }
  : null
```

- [ ] **Step 5: Pass replay props to `BevMap`**

Add this prop to the existing `BevMap` call:

```tsx
conflictReplay={conflictReplay}
```

- [ ] **Step 6: Make conflict list rows clickable**

Replace the conflict event row wrapper with a `<button>` that:

```tsx
const key = conflictEventKey(evt, i)
const isSelected = key === selectedConflictKey
```

Use this click handler:

```tsx
onClick={() => {
  if (isSelected) return
  setSelectedConflictKey(key)
  setPlaybackState('playing')
  setReplayNonce((prev) => prev + 1)
}}
```

Keep the existing row content, add `type='button'`, `aria-pressed={isSelected}`, `w-full text-left transition-colors`, and include a small `回放中` badge when selected.

- [ ] **Step 7: Add playback controls above or below the list**

When `selectedConflictEvent` is non-null, render compact controls in the conflict card:

```tsx
<div className='flex flex-wrap items-center gap-1 px-4 pb-2'>
  {[3, 6, 10].map((value) => (
    <button
      key={value}
      type='button'
      onClick={() => {
        setReplayWindowSec(value as ReplayWindowSec)
        setPlaybackState('playing')
        setReplayNonce((prev) => prev + 1)
      }}
      className='rounded border px-2 py-1 text-[10px] font-mono-cto'
    >
      {value}s
    </button>
  ))}
  {[0.5, 1, 2].map((value) => (
    <button
      key={value}
      type='button'
      onClick={() => setPlaybackSpeed(value as PlaybackSpeed)}
      className='rounded border px-2 py-1 text-[10px] font-mono-cto'
    >
      {value}x
    </button>
  ))}
  <button
    type='button'
    onClick={() => setPlaybackState(playbackState === 'playing' ? 'paused' : 'playing')}
    className='rounded border px-2 py-1 text-[10px] font-mono-cto'
  >
    {playbackState === 'playing' ? '暂停' : '播放'}
  </button>
  <button
    type='button'
    onClick={() => {
      setPlaybackState('playing')
      setReplayNonce((prev) => prev + 1)
    }}
    className='rounded border px-2 py-1 text-[10px] font-mono-cto'
  >
    重放
  </button>
  <button
    type='button'
    onClick={() => {
      setSelectedConflictKey(null)
      setPlaybackState('ended')
    }}
    className='rounded border px-2 py-1 text-[10px] font-mono-cto'
  >
    退出
  </button>
</div>
```

Style these buttons with existing `oklch(...)` colors to match the page.

## Task 3: BEV Conflict Replay Layer

**Files:**
- Modify: `traffic-fly-console/src/features/monitoring/bev-map.tsx`

- [ ] **Step 1: Import replay types and helper**

Add:

```ts
import {
  sliceReplayPoints,
  type ConflictReplayTracks,
  type PlaybackSpeed,
  type PlaybackState,
} from './conflict-replay-utils'
```

- [ ] **Step 2: Extend `BevMapProps`**

Add:

```ts
conflictReplay?: {
  tracks: ConflictReplayTracks
  playbackState: PlaybackState
  playbackSpeed: PlaybackSpeed
  replayNonce: number
  onPlaybackStateChange?: (state: PlaybackState) => void
} | null
```

- [ ] **Step 3: Create conflict vector source/layer**

Inside `BevMap`, add:

```ts
const conflictSource = useRef<VectorSource>(new VectorSource())
const [replayProgress, setReplayProgress] = useState(0)
```

During map initialization, create a `conflictLayer` after `activeLayer`:

```ts
const conflictLayer = new VectorLayer({
  source: conflictSource.current,
  style: (feature) => feature.get('style'),
  zIndex: 50,
})
```

Add it to `layers: [osmLayer, historicalLayer, vectorLayer, activeLayer, conflictLayer]`.

- [ ] **Step 4: Add local style factories**

Add functions in `bev-map.tsx`:

```ts
function conflictLineStyle(role: 'motor' | 'non_motor'): Style {
  const color = role === 'motor' ? 'rgba(56, 189, 248, 0.95)' : 'rgba(251, 146, 60, 0.95)'
  return new Style({ stroke: new Stroke({ color, width: 5 }) })
}

function conflictPointStyle(role: 'motor' | 'non_motor'): Style {
  const color = role === 'motor' ? 'rgba(56, 189, 248, 1)' : 'rgba(251, 146, 60, 1)'
  return new Style({
    image: new CircleStyle({
      radius: 7,
      fill: new Fill({ color }),
      stroke: new Stroke({ color: 'rgba(255,255,255,0.85)', width: 2 }),
    }),
  })
}

function conflictDistanceStyle(distanceLabel: string): Style {
  return new Style({
    stroke: new Stroke({ color: 'rgba(248, 250, 252, 0.85)', width: 2, lineDash: [5, 5] }),
    text: new Text({
      text: distanceLabel,
      font: '11px monospace',
      fill: new Fill({ color: 'rgba(248,250,252,0.95)' }),
      stroke: new Stroke({ color: 'rgba(0,0,0,0.65)', width: 3 }),
      offsetY: -8,
    }),
  })
}

function conflictRiskStyle(severity: string): Style {
  const color = severity === 'critical' ? 'rgba(239, 68, 68, 0.9)' : 'rgba(245, 158, 11, 0.9)'
  return new Style({
    image: new CircleStyle({
      radius: severity === 'critical' ? 16 : 12,
      fill: new Fill({ color: severity === 'critical' ? 'rgba(239, 68, 68, 0.18)' : 'rgba(245, 158, 11, 0.16)' }),
      stroke: new Stroke({ color, width: 3 }),
    }),
  })
}
```

- [ ] **Step 5: Animate replay progress**

Add an effect:

```ts
useEffect(() => {
  if (!conflictReplay || conflictReplay.playbackState !== 'playing') return
  let frame = 0
  const durationMs = conflictReplay.tracks.windowSec * 1000 / conflictReplay.playbackSpeed
  const started = performance.now()

  const tick = (now: number) => {
    const progress = Math.min(1, (now - started) / durationMs)
    setReplayProgress(progress)
    if (progress >= 1) {
      conflictReplay.onPlaybackStateChange?.('ended')
      return
    }
    frame = requestAnimationFrame(tick)
  }

  setReplayProgress(0)
  frame = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(frame)
}, [conflictReplay?.replayNonce, conflictReplay?.playbackState, conflictReplay?.playbackSpeed, conflictReplay?.tracks.windowSec])
```

- [ ] **Step 6: Draw conflict features**

Add an effect that clears `conflictSource.current`, slices motor/non-motor points by `replayProgress`, converts them with `worldToLonLat`, and adds:

- motor line when at least 2 points
- non-motor line when at least 2 points
- current motor point
- current non-motor point
- distance line when both current points exist
- risk point at midpoint of current points, or event motor/non_motor midpoint fallback

Each feature should set its `style` property from the style factories above.

- [ ] **Step 7: Fit once per selected event**

Add an effect keyed by `conflictReplay?.replayNonce` that fits the map view to the conflict layer extent when it has finite extent:

```ts
useEffect(() => {
  const map = mapInstance.current
  if (!map || !conflictReplay) return
  setTimeout(() => {
    const extent = conflictSource.current.getExtent()
    if (extent && isFinite(extent[0])) {
      map.getView().fit(extent, { padding: [70, 70, 70, 70], maxZoom: 21, duration: 450 })
    }
  }, 0)
}, [conflictReplay?.replayNonce])
```

- [ ] **Step 8: Add compact BEV replay status overlay**

In the JSX, above the stats overlay, render when `conflictReplay` exists:

```tsx
<div className='absolute top-2 left-2 z-20 rounded px-2 py-1.5 text-[10px] font-mono-cto' style={{ ... }}>
  <div>冲突回放 · {String(conflictReplay.tracks.event.severity ?? 'info').toUpperCase()}</div>
  <div>TTC {Number(conflictReplay.tracks.event.ttc_sec).toFixed(1)}s · 距离 {Number(conflictReplay.tracks.event.distance_m).toFixed(1)}m</div>
  {conflictReplay.tracks.hasInsufficientTrajectory && <div>轨迹不足 · 显示可用片段</div>}
  {conflictReplay.tracks.status === 'missing_world' && <div>缺少世界坐标</div>}
</div>
```

Guard numeric formatting with `Number.isFinite` in the final code.

## Task 4: UI Polish And Accessibility

**Files:**
- Modify: `traffic-fly-console/src/features/monitoring/index.tsx`
- Modify: `traffic-fly-console/src/features/monitoring/bev-map.tsx`

- [ ] **Step 1: Style selected conflict rows**

Use severity color for:

- left border or dot
- selected background
- selected `回放中` badge

Keep row height stable and avoid nested cards.

- [ ] **Step 2: Keep controls compact**

Use existing small button dimensions (`text-[10px]`, `font-mono-cto`, `rounded`, `border`) so the control area does not push metrics too far down.

- [ ] **Step 3: Add keyboard affordances**

Ensure clickable event rows are `<button type='button'>`, have `aria-pressed`, and keep visible focus via `focus-visible:outline`.

- [ ] **Step 4: Confirm no visible text overlaps**

Check the BEV overlay positions:

- replay status at top-left
- existing BEV stats at top-right
- legend at bottom-left
- mode controls at bottom-right from `Monitoring`

If top overlays collide on narrow screens, stack replay status below the existing stats with `max-w-[260px]`.

## Task 5: Verification

**Files:**
- Modify: `docs/TASKS.md`

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
cd traffic-fly-console
npm test -- conflict-replay-utils.test.ts
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd traffic-fly-console
npm run build
```

Expected: TypeScript and Vite build complete successfully.

- [ ] **Step 3: Update task documentation**

Add a new completed item under `docs/TASKS.md` quality/frontend records:

```md
| T-418 | 监控页冲突事件 BEV 回放 | ✅ | `traffic-fly-console/src/features/monitoring/` — 冲突事件列表可点击，BEV 叠加 motor/non_motor 回放层，支持播放/暂停/重放、倍速、3s/6s/10s 窗口和轨迹不足降级 |
```

- [ ] **Step 4: Record residual risks**

In the final implementation summary, mention:

- replay uses currently cached active/completed trajectories, so very old conflicts may only show event fallback points if their tracks aged out of the session;
- no Kafka/WebSocket schema change was made.

## Self-Review

- Spec coverage: clickable list, selected-row state, BEV replay layer, TTC/distance/severity display, 3s/6s/10s window, playback controls, insufficient trajectory fallback, no Kafka contract change, and frontend build are covered by Tasks 1-5.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation placeholders remain.
- Type consistency: `ConflictReplayEvent`, `ConflictReplayTracks`, `ReplayWindowSec`, `PlaybackSpeed`, and `PlaybackState` are defined in Task 1 and reused consistently in Tasks 2-3.
