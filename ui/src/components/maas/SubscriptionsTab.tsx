import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Button, Label, Spinner } from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import { getMaasSubscriptions, type MaasSubscription } from '../../api/client';
import { MaasUnavailableNotice } from './MaasUnavailableNotice';

// Code-split: RawYamlModal pulls in Monaco (see monacoSetup.ts) — same
// reasoning as RunDetail.tsx's lazy-loading of RunSettingsModal, so Monaco's
// bundle is only fetched when a row's "View YAML" is actually clicked, not on
// every visit to the MaaS Setup tab.
const RawYamlModal = lazy(() =>
  import('../RawYamlModal').then((m) => ({ default: m.RawYamlModal })),
);

const POLL_INTERVAL_MS = 25000;

function RateLimitChips({ sub }: { sub: MaasSubscription }) {
  if (sub.models.length === 0) return <span style={{ color: '#888' }}>—</span>;
  return (
    <>
      {sub.models.map((m) => (
        <div key={`${m.namespace}/${m.name}`} style={{ marginBottom: '0.2rem' }}>
          <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{m.name}</span>
          {m.token_rate_limits.map((rl, i) => (
            <Label key={i} isCompact style={{ marginLeft: '0.4rem' }}>
              {rl.limit} / {rl.window}
            </Label>
          ))}
        </div>
      ))}
    </>
  );
}

function OwnerChips({ owner }: { owner: MaasSubscription['owner'] }) {
  const groups = owner.groups ?? [];
  const users = owner.users ?? [];
  if (groups.length === 0 && users.length === 0) return <span style={{ color: '#888' }}>—</span>;
  return (
    <>
      {groups.map((g) => (
        <Label key={`g-${g}`} isCompact color="blue" style={{ marginRight: '0.3rem', marginBottom: '0.2rem' }}>
          {g}
        </Label>
      ))}
      {users.map((u) => (
        <Label key={`u-${u}`} isCompact style={{ marginRight: '0.3rem', marginBottom: '0.2rem' }}>
          {u}
        </Label>
      ))}
    </>
  );
}

export function SubscriptionsTab() {
  const [items, setItems] = useState<MaasSubscription[] | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<string | null | undefined>(undefined);
  const [yamlSub, setYamlSub] = useState<MaasSubscription | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchData() {
    const result = await getMaasSubscriptions();
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

  if (unavailableReason === undefined) return <Spinner size="md" aria-label="Loading subscriptions" />;
  if (unavailableReason) return <MaasUnavailableNotice reason={unavailableReason} />;
  if (!items) return null;

  return (
    <>
      <Table aria-label="MaaS subscriptions">
        <Thead>
          <Tr>
            <Th>Name</Th>
            <Th>Priority</Th>
            <Th>Phase</Th>
            <Th>Rate limits by model</Th>
            <Th>Granted to</Th>
            <Th screenReaderText="Actions" />
          </Tr>
        </Thead>
        <Tbody>
          {items.length === 0 ? (
            <Tr>
              <Td colSpan={6} style={{ color: '#888', fontStyle: 'italic' }}>
                No subscriptions found.
              </Td>
            </Tr>
          ) : (
            items.map((sub) => (
              <Tr key={`${sub.namespace}/${sub.name}`}>
                <Td>
                  <div style={{ fontWeight: 700 }}>{sub.display_name}</div>
                  <div style={{ fontSize: '0.78rem', color: '#888' }}>{sub.description}</div>
                  {sub.priority_conflict && (
                    <Label isCompact color="orange" style={{ marginTop: '0.2rem' }}>
                      ⚠ priority conflict
                    </Label>
                  )}
                </Td>
                <Td>{sub.priority ?? '—'}</Td>
                <Td>
                  <Label isCompact color={sub.ready ? 'green' : 'grey'}>
                    {sub.phase ?? 'Unknown'}
                  </Label>
                </Td>
                <Td><RateLimitChips sub={sub} /></Td>
                <Td><OwnerChips owner={sub.owner} /></Td>
                <Td>
                  <Button variant="link" isInline onClick={() => setYamlSub(sub)}>
                    View YAML
                  </Button>
                </Td>
              </Tr>
            ))
          )}
        </Tbody>
      </Table>

      {yamlSub !== null && (
        <Suspense fallback={<Spinner size="lg" aria-label="Loading editor" />}>
          <RawYamlModal
            title={`Subscription: ${yamlSub.display_name}`}
            downloadFileName={`${yamlSub.name}.yaml`}
            yamlText={yamlSub.raw_yaml}
            onClose={() => setYamlSub(null)}
          />
        </Suspense>
      )}
    </>
  );
}
