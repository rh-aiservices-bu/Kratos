import { useEffect, useState } from 'react';
import { getProgress, type TaskProgressEntry } from '../api/client';

interface Props {
  runId: string;
}

const STATUS_ICON: Record<TaskProgressEntry['status'], string> = {
  PENDING: '○',
  RUNNING: '◎',
  DONE: '✓',
  FAIL: '✗',
};

const STATUS_COLOR: Record<TaskProgressEntry['status'], string> = {
  PENDING: '#9e9e9e',
  RUNNING: '#1565c0',
  DONE: '#2e7d32',
  FAIL: '#c62828',
};

function formatTaskName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function TaskProgress({ runId }: Props) {
  const [tasks, setTasks] = useState<TaskProgressEntry[]>([]);

  useEffect(() => {
    getProgress(runId).then(setTasks).catch(() => {});
    const interval = setInterval(() => {
      getProgress(runId).then(setTasks).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [runId]);

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

        return (
          <div key={task.name} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {i > 0 && <span className="kratos-task-pipeline__arrow">→</span>}
            <div
              className={`kratos-task-chip kratos-task-chip--${task.status.toLowerCase()}`}
              style={{ '--task-color': color } as React.CSSProperties}
            >
              {isRunning ? (
                <span className="kratos-task-chip__spinner" />
              ) : (
                <span className="kratos-task-chip__icon">{STATUS_ICON[task.status]}</span>
              )}
              <span className="kratos-task-chip__name">{formatTaskName(task.name)}</span>
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
