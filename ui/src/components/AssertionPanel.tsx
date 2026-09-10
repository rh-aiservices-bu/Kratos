import type { AssertionState, TaskProgressEntry } from '../api/client';

interface Props {
  assertions: AssertionState[];
  taskProgress: TaskProgressEntry[];
}

const ASSERTION_COLORS: Record<AssertionState['status'], string> = {
  PENDING: '#9e9e9e',
  PASSING: '#2e7d32',
  FAILING: '#c62828',
};

const ASSERTION_BG: Record<AssertionState['status'], string> = {
  PENDING: '#f5f5f5',
  PASSING: '#f1f8f1',
  FAILING: '#fdf3f3',
};

const STATUS_ICON: Record<AssertionState['status'], string> = {
  PENDING: '○',
  PASSING: '✓',
  FAILING: '✗',
};

const TASK_STATUS_COLOR: Record<TaskProgressEntry['status'], string> = {
  PENDING: '#9e9e9e',
  RUNNING: '#1565c0',
  DONE: '#2e7d32',
  FAIL: '#c62828',
};

function formatValue(v: number | null): string {
  if (v === null) return '—';
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}

function formatName(name: string): string {
  return name
    .replace(/_pct$/i, '_percent')
    .replace(/_ms$/i, ' (ms)')
    .replace(/_rps$/i, ' (rps)')
    .replace(/_percent$/i, ' (%)')
    .replace(/_/g, ' ')
    .replace(/\bp(\d+)\b/gi, 'P$1')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

function formatTaskName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function AssertionCard({ a, muted }: { a: AssertionState; muted: boolean }) {
  const color = ASSERTION_COLORS[a.status];
  const bg = ASSERTION_BG[a.status];
  return (
    <div
      className="kratos-assertion-card"
      style={
        {
          '--assertion-color': color,
          '--assertion-bg': bg,
          opacity: muted ? 0.7 : 1,
          pointerEvents: muted ? 'none' : undefined,
        } as React.CSSProperties
      }
    >
      <span className="kratos-assertion-card__name">{formatName(a.name)}</span>
      <span className="kratos-assertion-card__value">
        {formatValue(a.value)}
        {a.expected_value != null && ` vs. expected ${formatValue(a.expected_value)}`}
      </span>
      {a.expression && (
        <span className="kratos-assertion-card__expr">target: {a.expression}</span>
      )}
      <span className="kratos-assertion-card__status">
        <span>{STATUS_ICON[a.status]}</span>
        <span>{a.status}</span>
      </span>
    </div>
  );
}

function AssertionGroup({
  label,
  taskStatus,
  assertions,
  muted,
}: {
  label: string;
  taskStatus: TaskProgressEntry['status'] | null;
  assertions: AssertionState[];
  muted: boolean;
}) {
  const borderColor = taskStatus ? TASK_STATUS_COLOR[taskStatus] : '#bbb';
  const statusLabel = taskStatus
    ? taskStatus.charAt(0) + taskStatus.slice(1).toLowerCase()
    : null;

  return (
    <div className="kratos-assertion-group" style={{ opacity: muted ? 0.72 : 1 }}>
      <div
        className="kratos-assertion-group__header"
        style={{ borderBottomColor: borderColor }}
      >
        <span className="kratos-assertion-group__title">{label}</span>
        {statusLabel && (
          <span
            className="kratos-assertion-group__status"
            style={{ color: borderColor }}
          >
            {statusLabel}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.5rem' }}>
        {assertions.map((a) => (
          <AssertionCard key={a.name} a={a} muted={false} />
        ))}
      </div>
    </div>
  );
}

export function AssertionPanel({ assertions, taskProgress }: Props) {
  if (assertions.length === 0) {
    return (
      <div>
        <p className="kratos-section-heading">Assertions</p>
        <p style={{ color: '#aaa', fontSize: '0.85rem', fontStyle: 'italic' }}>
          Waiting for assertion data…
        </p>
      </div>
    );
  }

  // Build lookup from task name → TaskProgressEntry for status labels
  const progressByName = new Map(taskProgress.map((t) => [t.name, t]));

  // Group assertions by task name (null = global)
  const byTask = new Map<string | null, AssertionState[]>();
  for (const a of assertions) {
    const key = a.task ?? null;
    if (!byTask.has(key)) byTask.set(key, []);
    byTask.get(key)!.push(a);
  }

  // Order: task groups in the order tasks appear in taskProgress, then global
  const taskGroups: Array<{ key: string; entries: AssertionState[]; progress: TaskProgressEntry | undefined }> = [];
  for (const tp of taskProgress) {
    if (byTask.has(tp.name)) {
      taskGroups.push({ key: tp.name, entries: byTask.get(tp.name)!, progress: tp });
    }
  }
  // Tasks not in taskProgress (shouldn't happen, but guard)
  for (const [key, entries] of byTask) {
    if (key !== null && !progressByName.has(key)) {
      taskGroups.push({ key, entries, progress: undefined });
    }
  }
  const globalEntries = byTask.get(null) ?? [];

  const runningIdx = taskProgress.findIndex((t) => t.status === 'RUNNING');

  return (
    <div>
      <p className="kratos-section-heading">Assertions</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {taskGroups.map(({ key, entries, progress }, idx) => {
          const isRunning = progress?.status === 'RUNNING';
          const isDone = progress?.status === 'DONE' || progress?.status === 'FAIL';
          // Mute completed tasks when there is still a running task after them
          const muted = isDone && runningIdx > idx;
          return (
            <AssertionGroup
              key={key}
              label={formatTaskName(key)}
              taskStatus={progress?.status ?? null}
              assertions={entries}
              muted={muted || (isDone && !isRunning)}
            />
          );
        })}
        {globalEntries.length > 0 && (
          <AssertionGroup
            key="__global__"
            label="Global"
            taskStatus={null}
            assertions={globalEntries}
            muted={false}
          />
        )}
      </div>
    </div>
  );
}
