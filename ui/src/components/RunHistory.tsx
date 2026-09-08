import { useEffect, useRef, useState } from 'react';
import { Button, Label, Spinner } from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import { listRuns, type Run } from '../api/client';

const ACTIVE_STATUSES = new Set(['PENDING', 'RUNNING']);

function StatusBadge({ status }: { status: string }) {
  const upper = status.toUpperCase();
  let colorClass = 'kratos-status-pend';
  if (upper === 'PASS') colorClass = 'kratos-status-pass';
  else if (upper === 'FAIL') colorClass = 'kratos-status-fail';
  else if (upper === 'RUNNING') colorClass = 'kratos-status-run';

  return (
    <Label className={colorClass} style={{ fontWeight: 700, fontSize: '0.72rem', letterSpacing: '0.04em' }}>
      {upper}
    </Label>
  );
}

interface Props {
  onViewRun: (runId: string) => void;
}

export function RunHistory({ onViewRun }: Props) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  async function fetchRuns() {
    try {
      const data = await listRuns();
      setRuns(data);
      setLoading(false);
      const hasActive = data.some((r) => ACTIVE_STATUSES.has(r.status.toUpperCase()));
      if (!hasActive) stopPolling();
    } catch {
      setLoading(false);
    }
  }

  useEffect(() => {
    void fetchRuns();
    intervalRef.current = setInterval(() => { void fetchRuns(); }, 3000);
    return () => stopPolling();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <Spinner aria-label="Loading run history" />;

  return (
    <>
      <p className="kratos-section-heading">Run History</p>
      <Table aria-label="Run history">
        <Thead>
          <Tr>
            <Th>Run ID</Th>
            <Th>Scenario</Th>
            <Th>Status</Th>
            <Th>Started</Th>
            <Th />
          </Tr>
        </Thead>
        <Tbody>
          {runs.length === 0 ? (
            <Tr>
              <Td colSpan={5} style={{ color: '#888', fontStyle: 'italic' }}>
                No runs yet.
              </Td>
            </Tr>
          ) : (
            runs.map((r) => (
              <Tr key={r.id}>
                <Td>
                  <span title={r.id} style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                    {r.id.slice(0, 8)}
                  </span>
                </Td>
                <Td>{r.scenario.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}</Td>
                <Td><StatusBadge status={r.status} /></Td>
                <Td style={{ fontSize: '0.85rem', color: '#555' }}>
                  {new Date(r.created_at).toLocaleString()}
                </Td>
                <Td>
                  <Button variant="link" isInline onClick={() => onViewRun(r.id)}>
                    View
                  </Button>
                </Td>
              </Tr>
            ))
          )}
        </Tbody>
      </Table>
    </>
  );
}
