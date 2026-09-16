import { useEffect, useState } from 'react';
import { Grid, GridItem, Page, PageSection } from '@patternfly/react-core';
import { MaasOverviewPage } from './components/maas/MaasOverviewPage';
import { RunDetail } from './components/RunDetail';
import { RunHistory } from './components/RunHistory';
import { RunTrigger } from './components/RunTrigger';
import { ScenarioList } from './components/ScenarioList';
import type { Scenario } from './api/client';

type AppView = { page: 'home' } | { page: 'maas' } | { page: 'run'; runId: string };

function getViewFromHash(): AppView {
  const match = window.location.hash.match(/^#run\/(.+)$/);
  if (match) return { page: 'run', runId: match[1] };
  if (window.location.hash === '#maas') return { page: 'maas' };
  return { page: 'home' };
}

function navigateTo(view: AppView): void {
  const hash = view.page === 'run' ? `#run/${view.runId}` : view.page === 'maas' ? '#maas' : '';
  window.history.pushState({}, '', window.location.pathname + hash);
}

function KratosMasthead({
  activeNav,
  onNavigate,
}: {
  activeNav: 'home' | 'maas' | null;
  onNavigate: (page: 'home' | 'maas') => void;
}) {
  return (
    <header className="kratos-masthead">
      <div className="kratos-masthead__logo">
        <span>&#9876;</span>
        <span>
          KR<span className="kratos-masthead__logo-accent">A</span>TOS
        </span>
      </div>
      <div className="kratos-masthead__divider" />
      <span className="kratos-masthead__subtitle">RHOAI Test Harness</span>
      {activeNav !== null && (
        <nav className="kratos-topnav">
          <button
            className={`kratos-topnav__link${activeNav === 'home' ? ' kratos-topnav__link--active' : ''}`}
            onClick={() => onNavigate('home')}
          >
            Runs
          </button>
          <button
            className={`kratos-topnav__link${activeNav === 'maas' ? ' kratos-topnav__link--active' : ''}`}
            onClick={() => onNavigate('maas')}
          >
            MaaS Setup
          </button>
        </nav>
      )}
    </header>
  );
}

function App() {
  const [view, setView] = useState<AppView>(getViewFromHash);
  const [triggerScenario, setTriggerScenario] = useState<Scenario | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  useEffect(() => {
    function onPopState() {
      setView(getViewFromHash());
    }
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  function handleRunStart(runId: string) {
    setTriggerScenario(null);
    setHistoryKey((k) => k + 1);
    const next: AppView = { page: 'run', runId };
    navigateTo(next);
    setView(next);
  }

  function handleViewRun(runId: string) {
    const next: AppView = { page: 'run', runId };
    navigateTo(next);
    setView(next);
  }

  function handleBack() {
    window.history.back();
  }

  function handleNavigate(page: 'home' | 'maas') {
    const next: AppView = { page };
    navigateTo(next);
    setView(next);
  }

  if (view.page === 'run') {
    return (
      <>
        <KratosMasthead activeNav={null} onNavigate={handleNavigate} />
        <RunDetail
          runId={view.runId}
          onBack={handleBack}
        />
      </>
    );
  }

  if (view.page === 'maas') {
    return (
      <>
        <KratosMasthead activeNav="maas" onNavigate={handleNavigate} />
        <MaasOverviewPage />
      </>
    );
  }

  return (
    <>
      <KratosMasthead activeNav="home" onNavigate={handleNavigate} />
      <Page>
        <PageSection>
          <Grid hasGutter>
            <GridItem span={4}>
              <ScenarioList onRun={setTriggerScenario} />
            </GridItem>
            <GridItem span={8}>
              <div style={{ maxHeight: 'calc(100vh - 120px)', overflowY: 'auto' }}>
                <RunHistory
                  key={historyKey}
                  onViewRun={handleViewRun}
                />
              </div>
            </GridItem>
          </Grid>
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
