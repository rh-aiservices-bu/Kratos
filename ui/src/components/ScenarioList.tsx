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

export function formatScenarioName(name: string): string {
  return name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

// Fixed display order for the built-in categories — mirrors
// harness/tests/test_scenarios.py's _KNOWN_CATEGORIES; keep both in sync.
// "Custom" is always rendered last, and always rendered even when empty, so
// anyone dropping a scenario YAML in without a `category:` field (or with
// one we don't recognize) immediately sees where it will land.
const CATEGORY_ORDER = [
  'Load Testing',
  'Rate Limiting',
  'Access Control',
  'Metrics Validation',
  'API Key Lifecycle',
  'Platform Health',
] as const;
const CUSTOM_CATEGORY = 'Custom';

function groupByCategory(scenarios: Scenario[]): Map<string, Scenario[]> {
  const groups = new Map<string, Scenario[]>();
  for (const category of CATEGORY_ORDER) groups.set(category, []);
  groups.set(CUSTOM_CATEGORY, []);

  for (const s of scenarios) {
    const key = groups.has(s.category) ? s.category : CUSTOM_CATEGORY;
    groups.get(key)!.push(s);
  }
  return groups;
}

interface Props {
  onRun: (scenario: Scenario) => void;
}

function ScenarioCard({ scenario, onRun }: { scenario: Scenario; onRun: (s: Scenario) => void }) {
  return (
    <Card>
      <CardBody style={{ padding: '0.75rem 1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="kratos-scenario-name" style={{ marginBottom: '0.25rem' }}>
              {formatScenarioName(scenario.name)}
            </div>
            <p style={{ margin: 0, color: '#666', fontSize: '0.8rem', lineHeight: 1.4 }}>
              {scenario.description}
            </p>
          </div>
          <Button variant="primary" onClick={() => onRun(scenario)} style={{ flexShrink: 0, alignSelf: 'center' }}>
            Run
          </Button>
        </div>
      </CardBody>
    </Card>
  );
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

  const groups = groupByCategory(scenarios);

  return (
    <Stack hasGutter>
      {[...CATEGORY_ORDER, CUSTOM_CATEGORY].map((category) => {
        const items = groups.get(category) ?? [];
        if (items.length === 0 && category !== CUSTOM_CATEGORY) return null;

        return (
          <StackItem key={category}>
            <p className="kratos-section-heading" style={{ marginBottom: '0.5rem' }}>
              {category}
            </p>
            {items.length === 0 ? (
              <p style={{ color: '#888', fontSize: '0.8rem', margin: 0 }}>
                No custom scenarios yet — add a scenario YAML under <code>scenarios/</code> with
                no <code>category:</code> field (or one of your own) and it will show up here.
              </p>
            ) : (
              <Stack hasGutter>
                {items.map((s) => (
                  <StackItem key={s.name} className="kratos-scenario-card">
                    <ScenarioCard scenario={s} onRun={onRun} />
                  </StackItem>
                ))}
              </Stack>
            )}
          </StackItem>
        );
      })}
    </Stack>
  );
}
