import { useEffect, useMemo, useRef, useState } from 'react';
import { Label, Spinner, TextInput } from '@patternfly/react-core';
import { Table, Tbody, Td, Th, Thead, Tr } from '@patternfly/react-table';
import {
  getMaasAuthPolicies,
  getMaasModels,
  getMaasSubscriptions,
  type MaasAuthPolicy,
  type MaasModel,
  type MaasSubscription,
} from '../../api/client';
import { MaasUnavailableNotice } from './MaasUnavailableNotice';

const POLL_INTERVAL_MS = 25000;

interface ResolvedRow {
  model: MaasModel;
  winningSubscription: MaasSubscription | null;
  matchingSubscriptions: MaasSubscription[];
  matchingPolicies: MaasAuthPolicy[];
  reachable: boolean;
}

function modelKey(namespace: string, name: string): string {
  return `${namespace}/${name}`;
}

// The whole point: resolve access the way MaaS itself would for a given set
// of candidate groups — highest-priority matching subscription wins the
// quota question, and a model is only actually reachable when a matching
// auth policy ALSO exists for one of these groups (see Catalog item I / C).
// Purely client-side over data already fetched — no new backend endpoint.
function resolveAccess(
  models: MaasModel[],
  subscriptions: MaasSubscription[],
  authPolicies: MaasAuthPolicy[],
  candidateGroups: string[],
): ResolvedRow[] {
  if (candidateGroups.length === 0) return [];

  return models.map((model) => {
    const key = modelKey(model.namespace, model.name);

    const matchingSubscriptions = subscriptions.filter(
      (s) =>
        s.owner.groups.some((g) => candidateGroups.includes(g)) &&
        s.models.some((m) => modelKey(m.namespace, m.name) === key),
    );
    const matchingPolicies = authPolicies.filter(
      (p) =>
        p.owner.groups.some((g) => candidateGroups.includes(g)) &&
        p.models.some((m) => modelKey(m.namespace, m.name) === key),
    );

    const winningSubscription =
      matchingSubscriptions.length === 0
        ? null
        : matchingSubscriptions.reduce((best, s) =>
            (s.priority ?? -Infinity) > (best.priority ?? -Infinity) ? s : best,
          );

    return {
      model,
      winningSubscription,
      matchingSubscriptions,
      matchingPolicies,
      reachable: matchingSubscriptions.length > 0 && matchingPolicies.length > 0,
    };
  });
}

export function AccessSimulatorTab() {
  const [models, setModels] = useState<MaasModel[] | null>(null);
  const [modelsUnavailable, setModelsUnavailable] = useState<string | null | undefined>(undefined);
  const [subscriptions, setSubscriptions] = useState<MaasSubscription[] | null>(null);
  const [subscriptionsUnavailable, setSubscriptionsUnavailable] = useState<string | null | undefined>(undefined);
  const [authPolicies, setAuthPolicies] = useState<MaasAuthPolicy[] | null>(null);
  const [authPoliciesUnavailable, setAuthPoliciesUnavailable] = useState<string | null | undefined>(undefined);
  const [groupsInput, setGroupsInput] = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchData() {
    const [modelsResult, subsResult, authResult] = await Promise.all([
      getMaasModels(),
      getMaasSubscriptions(),
      getMaasAuthPolicies(),
    ]);
    if (modelsResult.available) {
      setModels(modelsResult.items);
      setModelsUnavailable(null);
    } else {
      setModels(null);
      setModelsUnavailable(modelsResult.reason ?? 'unknown');
    }
    if (subsResult.available) {
      setSubscriptions(subsResult.items);
      setSubscriptionsUnavailable(null);
    } else {
      setSubscriptions(null);
      setSubscriptionsUnavailable(subsResult.reason ?? 'unknown');
    }
    if (authResult.available) {
      setAuthPolicies(authResult.items);
      setAuthPoliciesUnavailable(null);
    } else {
      setAuthPolicies(null);
      setAuthPoliciesUnavailable(authResult.reason ?? 'unknown');
    }
  }

  useEffect(() => {
    void fetchData();
    intervalRef.current = setInterval(() => { void fetchData(); }, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current);
    };
  }, []);

  const candidateGroups = useMemo(
    () => groupsInput.split(',').map((g) => g.trim()).filter(Boolean),
    [groupsInput],
  );

  const resolved = useMemo(
    () => resolveAccess(models ?? [], subscriptions ?? [], authPolicies ?? [], candidateGroups),
    [models, subscriptions, authPolicies, candidateGroups],
  );

  if (modelsUnavailable === undefined) return <Spinner size="md" aria-label="Loading access simulator" />;
  if (modelsUnavailable) return <MaasUnavailableNotice reason={modelsUnavailable} />;
  if (subscriptionsUnavailable) return <MaasUnavailableNotice reason={subscriptionsUnavailable} />;
  if (authPoliciesUnavailable) return <MaasUnavailableNotice reason={authPoliciesUnavailable} />;

  return (
    <>
      <p style={{ color: '#555', marginBottom: '0.75rem' }}>
        Enter a candidate set of groups (comma-separated) to see which subscription would win by
        priority for each model, and whether that group set can actually reach it — the same
        resolution MaaS itself performs, computed here from live subscriptions and auth policies.
      </p>
      <TextInput
        type="text"
        aria-label="Candidate groups"
        placeholder="e.g. system:authenticated, premium-users"
        value={groupsInput}
        onChange={(_evt, value) => setGroupsInput(value)}
        style={{ maxWidth: '500px', marginBottom: '1rem' }}
      />

      {candidateGroups.length === 0 ? (
        <p style={{ color: '#888', fontStyle: 'italic' }}>
          Enter one or more group names above to simulate access resolution.
        </p>
      ) : (
        <Table aria-label="Access resolution simulation">
          <Thead>
            <Tr>
              <Th>Model</Th>
              <Th>Resolved subscription</Th>
              <Th modifier="wrap">Matching auth policies</Th>
              <Th>Reachable</Th>
            </Tr>
          </Thead>
          <Tbody>
            {resolved.map((row) => (
              <Tr key={modelKey(row.model.namespace, row.model.name)}>
                <Td>
                  <div style={{ fontWeight: 700 }}>{row.model.display_name}</div>
                  <div style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: '#888' }}>
                    {row.model.namespace}
                  </div>
                </Td>
                <Td>
                  {row.winningSubscription ? (
                    <>
                      <Label isCompact color="blue">
                        {row.winningSubscription.display_name} (p{row.winningSubscription.priority ?? '—'})
                      </Label>
                      {row.matchingSubscriptions.length > 1 && (
                        <div style={{ fontSize: '0.72rem', color: '#888', marginTop: '0.2rem' }}>
                          beat {row.matchingSubscriptions.length - 1} other matching subscription
                          {row.matchingSubscriptions.length > 2 ? 's' : ''}
                        </div>
                      )}
                    </>
                  ) : (
                    <span style={{ color: '#888' }}>no quota for this group set</span>
                  )}
                </Td>
                <Td>
                  {row.matchingPolicies.length === 0 ? (
                    <span style={{ color: '#888' }}>none</span>
                  ) : (
                    row.matchingPolicies.map((p) => (
                      <Label key={p.name} isCompact color="blue" style={{ marginRight: '0.3rem', marginBottom: '0.2rem' }}>
                        {p.display_name}
                      </Label>
                    ))
                  )}
                </Td>
                <Td>
                  <Label isCompact color={row.reachable ? 'green' : 'red'}>
                    {row.reachable ? '✓ reachable' : '✗ not reachable'}
                  </Label>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </>
  );
}
