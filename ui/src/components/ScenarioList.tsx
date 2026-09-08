import { useEffect, useState } from 'react';
import {
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

interface Props {
  onRun: (scenario: Scenario) => void;
}

export function ScenarioList({ onRun }: Props) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listScenarios()
      .then(setScenarios)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <Spinner aria-label="Loading scenarios" />;
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
      {scenarios.map((s) => (
        <StackItem key={s.name}>
          <Card>
            <CardTitle>{s.name}</CardTitle>
            <CardBody>
              <p>{s.description}</p>
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
