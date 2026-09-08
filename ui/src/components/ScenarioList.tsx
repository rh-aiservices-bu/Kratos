import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  EmptyState,
  EmptyStateBody,
  Spinner,
  Stack,
  StackItem,
} from '@patternfly/react-core';
import { listScenarios, type Scenario } from '../api/client';

function formatScenarioName(name: string): string {
  return name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

interface Props {
  onRun: (scenario: Scenario) => void;
}

export function ScenarioList({ onRun }: Props) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listScenarios()
      .then(setScenarios)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load scenarios'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <Spinner aria-label="Loading scenarios" />;

  if (error) {
    return (
      <Alert
        variant="danger"
        title="Could not load scenarios"
        actionLinks={
          <Button variant="link" onClick={load}>Retry</Button>
        }
      >
        {error}
      </Alert>
    );
  }

  if (scenarios.length === 0) {
    return (
      <EmptyState>
        <EmptyStateBody>No scenarios available.</EmptyStateBody>
      </EmptyState>
    );
  }

  return (
    <Stack hasGutter>
      <StackItem>
        <p className="kratos-section-heading">Scenarios</p>
      </StackItem>
      {scenarios.map((s) => (
        <StackItem key={s.name} className="kratos-scenario-card">
          <Card>
            <CardTitle>
              <span className="kratos-scenario-name">{formatScenarioName(s.name)}</span>
            </CardTitle>
            <CardBody>
              <p style={{ marginBottom: '1rem', color: '#555' }}>{s.description}</p>
              <Button variant="primary" onClick={() => onRun(s)}>
                Run
              </Button>
            </CardBody>
          </Card>
        </StackItem>
      ))}
    </Stack>
  );
}
