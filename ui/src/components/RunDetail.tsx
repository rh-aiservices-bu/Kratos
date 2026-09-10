import { useEffect, useState } from 'react';
import { Button, Grid, GridItem, Page, PageSection, Spinner } from '@patternfly/react-core';
import { AssertionPanel } from './AssertionPanel';
import { LogStream } from './LogStream';
import { TaskProgress } from './TaskProgress';
import { getAssertions, getProgress, getRun, type AssertionState, type Run, type TaskProgressEntry } from '../api/client';

function formatScenarioName(name: string): string {
  return name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function StatusDot({ status }: { status: string }) {
  const upper = status.toUpperCase();
  const color =
    upper === 'PASS' ? '#2e7d32'
    : upper === 'FAIL' ? '#c62828'
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

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, []);

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
    getProgress(runId).then(setTaskProgress).catch(() => {});
    const interval = setInterval(() => {
      getProgress(runId).then(setTaskProgress).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [runId]);

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
              <span
                className="kratos-run-detail-meta__item"
                title={runId}
                style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: '#aaa' }}
              >
                {runId.slice(0, 12)}…
              </span>
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
    </Page>
  );
}
