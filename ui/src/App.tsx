import { useState } from 'react';
import { Page, PageSection, Title } from '@patternfly/react-core';
import { AssertionPanel } from './components/AssertionPanel';
import { LogStream, type AssertionState } from './components/LogStream';
import { RunHistory } from './components/RunHistory';
import { RunTrigger } from './components/RunTrigger';
import { ScenarioList } from './components/ScenarioList';
import type { Scenario } from './api/client';

function App() {
  const [triggerScenario, setTriggerScenario] = useState<Scenario | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [assertions, setAssertions] = useState<AssertionState[]>([]);
  const [historyKey, setHistoryKey] = useState(0);

  function handleRunStart(runId: string) {
    setActiveRunId(runId);
    setAssertions([]);
    setTriggerScenario(null);
    setHistoryKey((k) => k + 1);
  }

  return (
    <Page>
      <PageSection>
        <Title headingLevel="h1" size="xl">
          Kratos — RHOAI MaaS Test Harness
        </Title>
      </PageSection>

      <PageSection>
        <ScenarioList onRun={setTriggerScenario} />
      </PageSection>

      {activeRunId !== null && (
        <PageSection>
          <LogStream runId={activeRunId} onAssertionUpdate={setAssertions} />
          <AssertionPanel assertions={assertions} />
        </PageSection>
      )}

      <PageSection>
        <Title headingLevel="h2" size="lg">
          Run History
        </Title>
        <RunHistory key={historyKey} />
      </PageSection>

      {triggerScenario !== null && (
        <RunTrigger
          scenario={triggerScenario}
          onConfirm={handleRunStart}
          onCancel={() => setTriggerScenario(null)}
        />
      )}
    </Page>
  );
}

export default App;
