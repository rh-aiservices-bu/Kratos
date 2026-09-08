import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  CardBody,
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
            <CardBody style={{ padding: '0.75rem 1rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="kratos-scenario-name" style={{ marginBottom: '0.25rem' }}>
                    {formatScenarioName(s.name)}
                  </div>
                  <p style={{ margin: 0, color: '#666', fontSize: '0.8rem', lineHeight: 1.4 }}>
                    {s.description}
                  </p>
                </div>
                <Button variant="primary" onClick={() => onRun(s)} style={{ flexShrink: 0, alignSelf: 'center' }}>
                  Run
                </Button>
              </div>
            </CardBody>
          </Card>
        </StackItem>
      ))}
    </Stack>
  );
}
