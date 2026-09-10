import { useEffect, useState } from 'react';
import type { TaskProgressEntry } from '../api/client';

interface Props {
  tasks: TaskProgressEntry[];
}

const STATUS_ICON: Record<TaskProgressEntry['status'], string> = {
  PENDING: '○',
  RUNNING: '◎',
  DONE: '✓',
  FAIL: '✗',
  CANCELLED: '⊘',
};

const STATUS_COLOR: Record<TaskProgressEntry['status'], string> = {
  PENDING: '#9e9e9e',
  RUNNING: '#1565c0',
  DONE: '#2e7d32',
  FAIL: '#c62828',
  CANCELLED: '#b26a00',
};

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

/** Re-renders once a second so a RUNNING task's elapsed time visibly ticks up
 * between the 2s progress polls, without the backend ever pushing a live number. */
function useTick(active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
}

const ASSERTION_BADGE_COLOR: Record<string, string> = {
  PASSING: '#2e7d32',
  FAILING: '#c62828',
  PENDING: '#9e9e9e',
};

export function formatTaskName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function TaskProgress({ tasks }: Props) {
  useTick(tasks.some((t) => t.status === 'RUNNING' && !!t.started_at));

  if (tasks.length === 0) return null;

  return (
    <div className="kratos-task-pipeline">
      {tasks.map((task, i) => {
        const color = STATUS_COLOR[task.status];
        const isRunning = task.status === 'RUNNING';
        const pct =
          task.progress && task.progress.total > 0
            ? task.status === 'DONE'
              ? 100
              : Math.round((task.progress.current / task.progress.total) * 100)
            : null;
        const badgeColor = task.assertions_status
          ? ASSERTION_BADGE_COLOR[task.assertions_status]
          : null;
        const durationLabel =
          typeof task.duration_ms === 'number'
            ? formatDuration(task.duration_ms)
            : isRunning && task.started_at
              ? formatDuration(Date.now() - new Date(task.started_at).getTime())
              : null;

        return (
          <div key={task.name} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {i > 0 && <span className="kratos-task-pipeline__arrow">→</span>}
            <div
              className={`kratos-task-chip kratos-task-chip--${task.status.toLowerCase()}`}
              style={{ '--task-color': color } as React.CSSProperties}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                {isRunning ? (
                  <span className="kratos-task-chip__spinner" />
                ) : (
                  <span className="kratos-task-chip__icon">{STATUS_ICON[task.status]}</span>
                )}
                <span className="kratos-task-chip__name">{formatTaskName(task.name)}</span>
                {durationLabel && (
                  <span className="kratos-task-chip__duration">{durationLabel}</span>
                )}
                {badgeColor && (
                  <span
                    className="kratos-task-chip__assertion-badge"
                    style={{ background: badgeColor }}
                    title={`Assertions: ${task.assertions_status}`}
                  />
                )}
              </div>
              {pct !== null && (
                <div className="kratos-task-chip__progress-wrap">
                  <div className="kratos-task-chip__progress-bar">
                    <div
                      className="kratos-task-chip__progress-fill"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="kratos-task-chip__progress-label">
                    {task.progress!.current} / {task.progress!.total}
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
