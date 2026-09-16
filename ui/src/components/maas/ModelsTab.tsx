import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Button, Label, Spinner } from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import { getMaasModels, type MaasModel } from '../../api/client';
import { MaasUnavailableNotice } from './MaasUnavailableNotice';

// Code-split: RawYamlModal pulls in Monaco (see monacoSetup.ts) — same
// reasoning as RunDetail.tsx's lazy-loading of RunSettingsModal, so Monaco's
// bundle is only fetched when a row's "View YAML" is actually clicked, not on
// every visit to the MaaS Setup tab.
const RawYamlModal = lazy(() =>
  import('../RawYamlModal').then((m) => ({ default: m.RawYamlModal })),
);

const POLL_INTERVAL_MS = 25000;

function SubscriptionChips({ subs }: { subs: MaasModel['subscriptions'] }) {
  if (subs.length === 0) return <span style={{ color: '#888' }}>—</span>;
  return (
    <>
      {subs.map((s) => (
        <Label key={s.name} isCompact color="blue" style={{ marginRight: '0.3rem', marginBottom: '0.2rem' }}>
          {s.display_name ?? s.name}
        </Label>
      ))}
    </>
  );
}

// Answers "is this model served by OpenShift AI itself, or routed out to a
// third-party provider?" — the badge itself always reads Internal/External;
// the actual backing kind (LLMInferenceService, ExternalModel, ...) is shown
// underneath so the distinction is never ambiguous even for a future kind
// this UI doesn't special-case yet.
function HostingBadge({ model }: { model: MaasModel }) {
  const isExternal = model.hosting === 'external';
  return (
    <div>
      <Label isCompact color={isExternal ? 'purple' : 'blue'}>
        {isExternal ? 'External' : 'Internal'}
      </Label>
      <div style={{ fontSize: '0.78rem', fontFamily: 'monospace', color: '#444', marginTop: '0.25rem' }}>
        {model.namespace}
      </div>
      <div style={{ fontSize: '0.72rem', color: '#888' }}>
        {model.kind ?? 'Unknown kind'}
      </div>
      {typeof model.serving?.replicas === 'number' && (
        <div style={{ fontSize: '0.72rem', color: '#888' }}>
          {model.serving.replicas} replica{model.serving.replicas === 1 ? '' : 's'}
        </div>
      )}
    </div>
  );
}

export function ModelsTab() {
  const [items, setItems] = useState<MaasModel[] | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<string | null | undefined>(undefined);
  const [yamlModel, setYamlModel] = useState<MaasModel | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchData() {
    const result = await getMaasModels();
    if (result.available) {
      setItems(result.items);
      setUnavailableReason(null);
    } else {
      setItems(null);
      setUnavailableReason(result.reason ?? 'unknown');
    }
  }

  useEffect(() => {
    void fetchData();
    intervalRef.current = setInterval(() => { void fetchData(); }, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, []);

  if (unavailableReason === undefined) return <Spinner size="md" aria-label="Loading models" />;
  if (unavailableReason) return <MaasUnavailableNotice reason={unavailableReason} />;
  if (!items) return null;

  return (
    <>
      <Table aria-label="MaaS models">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Hosting</Th>
            <Th>Status</Th>
            <Th>Endpoint</Th>
            <Th>Subscriptions</Th>
            <Th screenReaderText="Actions" />
          </Tr>
        </Thead>
        <Tbody>
          {items.length === 0 ? (
            <Tr>
              <Td colSpan={6} style={{ color: '#888', fontStyle: 'italic' }}>
                No models found.
              </Td>
            </Tr>
          ) : (
            items.map((model) => (
              <Tr key={`${model.namespace}/${model.name}`}>
                <Td>
                  <div style={{ fontWeight: 700 }}>{model.display_name}</div>
                  <div style={{ fontSize: '0.78rem', color: '#888' }}>{model.description}</div>
                </Td>
                <Td><HostingBadge model={model} /></Td>
                <Td>
                  <Label isCompact color={model.ready ? 'green' : 'red'}>
                    {model.phase ?? (model.ready ? 'Ready' : 'Not ready')}
                  </Label>
                </Td>
                <Td>
                  {model.endpoint ? (
                    <span style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{model.endpoint}</span>
                  ) : (
                    <span style={{ color: '#888' }}>—</span>
                  )}
                </Td>
                <Td><SubscriptionChips subs={model.subscriptions} /></Td>
                <Td>
                  <Button variant="link" isInline onClick={() => setYamlModel(model)}>
                    View YAML
                  </Button>
                </Td>
              </Tr>
            ))
          )}
        </Tbody>
      </Table>

      {yamlModel !== null && (
        <Suspense fallback={<Spinner size="lg" aria-label="Loading editor" />}>
          <RawYamlModal
            title={`Model: ${yamlModel.display_name}`}
            downloadFileName={`${yamlModel.name}.yaml`}
            yamlText={yamlModel.raw_yaml}
            onClose={() => setYamlModel(null)}
          />
        </Suspense>
      )}
    </>
  );
}
