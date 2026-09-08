import { useState } from 'react';
import { Page, PageSection } from '@patternfly/react-core';
import { RunDetail } from './components/RunDetail';
import { RunHistory } from './components/RunHistory';
import { RunTrigger } from './components/RunTrigger';
import { ScenarioList } from './components/ScenarioList';
import type { Scenario } from './api/client';

type AppView = { page: 'home' } | { page: 'run'; runId: string };

function KratosMasthead() {
  return (
    <header className="kratos-masthead">
      <div className="kratos-masthead__logo">
        <span>&#9876;</span>
        <span>
          KR<span className="kratos-masthead__logo-accent">A</span>TOS
        </span>
      </div>
      <div className="kratos-masthead__divider" />
      <span className="kratos-masthead__subtitle">RHOAI MaaS Test Harness</span>
    </header>
  );
}

function App() {
  const [view, setView] = useState<AppView>({ page: 'home' });
  const [triggerScenario, setTriggerScenario] = useState<Scenario | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  function handleRunStart(runId: string) {
    setTriggerScenario(null);
    setHistoryKey((k) => k + 1);
    setView({ page: 'run', runId });
  }

  if (view.page === 'run') {
    return (
      <>
        <KratosMasthead />
        <RunDetail
          runId={view.runId}
          onBack={() => setView({ page: 'home' })}
        />
      </>
    );
  }

  return (
    <>
      <KratosMasthead />
      <Page>
        <PageSection>
          <ScenarioList onRun={setTriggerScenario} />
        </PageSection>

        <PageSection>
          <RunHistory
            key={historyKey}
            onViewRun={(runId) => setView({ page: 'run', runId })}
          />
        </PageSection>
      </Page>

      {triggerScenario !== null && (
        <RunTrigger
          scenario={triggerScenario}
          onConfirm={handleRunStart}
          onCancel={() => setTriggerScenario(null)}
        />
      )}
    </>
  );
}

export default App;
