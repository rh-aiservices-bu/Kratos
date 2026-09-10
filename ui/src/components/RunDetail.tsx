import { lazy, Suspense, useEffect, useState } from 'react';
import { Button, Grid, GridItem, Page, PageSection, Spinner } from '@patternfly/react-core';
import { AssertionPanel } from './AssertionPanel';
import { LogStream } from './LogStream';
import { TaskProgress } from './TaskProgress';
import {
  getAssertions,
  getProgress,
  getRun,
  stopRun,
  type AssertionState,
  type Run,
  type TaskProgressEntry,
} from '../api/client';

const ACTIVE_STATUSES = new Set(['PENDING', 'RUNNING']);

// Code-split: RunSettingsModal pulls in Monaco (self-hosted, see monacoSetup.ts),
// a sizeable bundle not worth loading for every run view when most never open it.
const RunSettingsModal = lazy(() =>
  import('./RunSettingsModal').then((m) => ({ default: m.RunSettingsModal }))
);

function formatScenarioName(name: string): string {
  return name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

function StatusDot({ status }: { status: string }) {
  const upper = status.toUpperCase();
  const color =
    upper === 'PASS' ? '#2e7d32'
    : upper === 'FAIL' ? '#c62828'
    : upper === 'CANCELLED' ? '#b26a00'
    : upper === 'RUNNING' ? '#1565c0'
    : '#9e9e9e';
  return (
    <span
      style={{
        display: 'inline-block',
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: color,
        marginRight: '0.4rem',
        verticalAlign: 'middle',
      }}
    />
  );
}

interface Props {
  runId: string;
  onBack: () => void;
}

export function RunDetail({ runId, onBack }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [assertions, setAssertions] = useState<AssertionState[]>([]);
  const [taskProgress, setTaskProgress] = useState<TaskProgressEntry[]>([]);
  const [runStartedAt, setRunStartedAt] = useState<string | undefined>(undefined);
  const [stopping, setStopping] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [, setTick] = useState(0);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, []);

  // Re-render once a second so the total elapsed time visibly ticks up between
  // the 4s /api/runs/{id} polls below, without the backend pushing a live number.
  useEffect(() => {
    if (!run || !ACTIVE_STATUSES.has(run.status.toUpperCase())) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [run]);

  useEffect(() => {
    getRun(runId).then(setRun).catch(console.error);
    const interval = setInterval(() => {
      getRun(runId)
        .then((r) => {
          setRun(r);
          if (r.status !== 'RUNNING' && r.status !== 'PENDING') {
            clearInterval(interval);
          }
        })
        .catch(console.error);
    }, 4000);
    return () => clearInterval(interval);
  }, [runId]);

  useEffect(() => {
    getAssertions(runId).then(setAssertions).catch(() => {});
    const interval = setInterval(() => {
      getAssertions(runId).then(setAssertions).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [runId]);

  useEffect(() => {
    function applyProgress(p: { tasks: TaskProgressEntry[]; run_started_at?: string }) {
      setTaskProgress(p.tasks);
      if (p.run_started_at) setRunStartedAt(p.run_started_at);
    }
    getProgress(runId).then(applyProgress).catch(() => {});
    const interval = setInterval(() => {
      getProgress(runId).then(applyProgress).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [runId]);

  async function handleStop() {
    if (!window.confirm('Stop this run? Already-running work will be cancelled.')) return;
    setStopping(true);
    try {
      await stopRun(runId);
      getRun(runId).then(setRun).catch(() => {});
    } catch (err) {
      console.error(err);
    } finally {
      setStopping(false);
    }
  }

  return (
    <Page>
      <PageSection>
        <div className="kratos-run-detail-bar">
          <Button variant="link" isInline onClick={onBack}>
            ← Back
          </Button>

          {run ? (
            <div className="kratos-run-detail-meta">
              <span className="kratos-run-detail-meta__item">
                <strong>{formatScenarioName(run.scenario)}</strong>
              </span>
              <span className="kratos-run-detail-meta__item">
                <StatusDot status={run.status} />
                <strong>{run.status}</strong>
              </span>
              <span className="kratos-run-detail-meta__item">
                Started: <strong>{new Date(run.created_at).toLocaleString()}</strong>
              </span>
              {(() => {
                const isActive = ACTIVE_STATUSES.has(run.status.toUpperCase());
                const durationMs = isActive
                  ? runStartedAt
                    ? Date.now() - new Date(runStartedAt).getTime()
                    : null
                  : (run.duration_ms ?? null);
                return durationMs !== null ? (
                  <span className="kratos-run-detail-meta__item">
                    Duration: <strong>{formatDuration(durationMs)}</strong>
                  </span>
                ) : null;
              })()}
              <span
                className="kratos-run-detail-meta__item"
                title={runId}
                style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: '#aaa' }}
              >
                {runId.slice(0, 12)}…
              </span>
              <Button variant="link" isInline onClick={() => setShowSettings(true)}>
                View Settings
              </Button>
              {ACTIVE_STATUSES.has(run.status.toUpperCase()) && (
                <Button
                  variant="danger"
                  isInline
                  isLoading={stopping}
                  isDisabled={stopping}
                  onClick={() => void handleStop()}
                >
                  Stop
                </Button>
              )}
            </div>
          ) : (
            <Spinner size="sm" aria-label="Loading run" />
          )}
        </div>

        <TaskProgress tasks={taskProgress} />

        <Grid hasGutter>
          <GridItem span={8}>
            <p className="kratos-section-heading">Live Logs</p>
            <LogStream runId={runId} />
          </GridItem>
          <GridItem span={4}>
            <AssertionPanel assertions={assertions} taskProgress={taskProgress} />
          </GridItem>
        </Grid>
      </PageSection>

      {showSettings && (
        <Suspense fallback={<Spinner size="lg" aria-label="Loading editor" />}>
          <RunSettingsModal runId={runId} onClose={() => setShowSettings(false)} />
        </Suspense>
      )}
    </Page>
  );
}
