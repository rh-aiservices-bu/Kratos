import { useEffect, useState } from 'react';
import { Spinner } from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import { listRuns, type Run } from '../api/client';

export function RunHistory() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner aria-label="Loading run history" />;

  return (
    <Table aria-label="Run history">
      <Thead>
        <Tr>
          <Th>Run ID</Th>
          <Th>Scenario</Th>
          <Th>Status</Th>
          <Th>Started</Th>
        </Tr>
      </Thead>
      <Tbody>
        {runs.map((r) => (
          <Tr key={r.id}>
            <Td>{r.id.slice(0, 8)}</Td>
            <Td>{r.scenario}</Td>
            <Td>{r.status}</Td>
            <Td>{new Date(r.created_at).toLocaleString()}</Td>
          </Tr>
        ))}
        {runs.length === 0 && (
          <Tr>
            <Td colSpan={4}>No runs yet.</Td>
          </Tr>
        )}
      </Tbody>
    </Table>
  );
}
