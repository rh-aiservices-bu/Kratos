import { fireEvent, render, screen } from '@testing-library/react';
import { AccessSimulatorTab } from './AccessSimulatorTab';
import * as client from '../../api/client';
import type { MaasAuthPolicy, MaasModel, MaasSubscription } from '../../api/client';

jest.mock('../../api/client');

const mockGetModels = client.getMaasModels as jest.MockedFunction<typeof client.getMaasModels>;
const mockGetSubscriptions = client.getMaasSubscriptions as jest.MockedFunction<
  typeof client.getMaasSubscriptions
>;
const mockGetAuthPolicies = client.getMaasAuthPolicies as jest.MockedFunction<
  typeof client.getMaasAuthPolicies
>;

const modelX: MaasModel = {
  name: 'model-x',
  namespace: 'llm',
  display_name: 'Model X',
  description: '',
  kind: 'LLMInferenceService',
  hosting: 'internal',
  backing_name: 'model-x',
  phase: 'Ready',
  ready: true,
  endpoint: null,
  subscriptions: [],
  has_auth_policy: null,
  gateway_access_label: null,
  external_providers: [],
  serving: null,
  raw: {},
  raw_yaml: '',
};

const freeSub: MaasSubscription = {
  name: 'free-tier',
  namespace: 'models-as-a-service',
  display_name: 'Free Tier',
  description: '',
  priority: 10,
  owner: { groups: ['system:authenticated'], users: [] },
  models: [{ name: 'model-x', namespace: 'llm', token_rate_limits: [] }],
  phase: 'Active',
  ready: true,
  priority_conflict: false,
  raw: {},
  raw_yaml: '',
};

const premiumSub: MaasSubscription = {
  ...freeSub,
  name: 'premium-tier',
  display_name: 'Premium Tier',
  priority: 20,
  owner: { groups: ['premium-users'], users: [] },
};

const authPolicy: MaasAuthPolicy = {
  name: 'model-x-access',
  namespace: 'models-as-a-service',
  display_name: 'Model X Access',
  owner: { groups: ['system:authenticated'], users: [] },
  models: [{ name: 'model-x', namespace: 'llm' }],
  ready: true,
  raw_yaml: '',
};

function mockAll(
  models: MaasModel[],
  subscriptions: MaasSubscription[],
  authPolicies: MaasAuthPolicy[],
) {
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: models });
  mockGetSubscriptions.mockResolvedValue({ available: true, reason: null, items: subscriptions });
  mockGetAuthPolicies.mockResolvedValue({ available: true, reason: null, items: authPolicies });
}

test('prompts for input before any groups are entered', async () => {
  mockAll([modelX], [freeSub], [authPolicy]);

  render(<AccessSimulatorTab />);

  expect(await screen.findByText(/enter one or more group names/i)).toBeInTheDocument();
});

test('resolves the highest-priority matching subscription and marks the model reachable', async () => {
  mockAll([modelX], [freeSub, premiumSub], [authPolicy]);

  render(<AccessSimulatorTab />);

  const input = await screen.findByPlaceholderText(/system:authenticated/i);
  fireEvent.change(input, { target: { value: 'system:authenticated' } });

  expect(await screen.findByText(/Free Tier \(p10\)/)).toBeInTheDocument();
  expect(screen.getByText('✓ reachable')).toBeInTheDocument();
  expect(screen.getByText('Model X Access')).toBeInTheDocument();
});

test('picks the higher-priority subscription when the group set matches multiple', async () => {
  const bothGroupsSub = { ...premiumSub, owner: { groups: ['system:authenticated'], users: [] } };
  mockAll([modelX], [freeSub, bothGroupsSub], [authPolicy]);

  render(<AccessSimulatorTab />);

  const input = await screen.findByPlaceholderText(/system:authenticated/i);
  fireEvent.change(input, { target: { value: 'system:authenticated' } });

  expect(await screen.findByText(/Premium Tier \(p20\)/)).toBeInTheDocument();
  expect(screen.getByText(/beat 1 other matching subscription/)).toBeInTheDocument();
});

test('shows not reachable when there is quota but no matching auth policy', async () => {
  mockAll([modelX], [freeSub], []);

  render(<AccessSimulatorTab />);

  const input = await screen.findByPlaceholderText(/system:authenticated/i);
  fireEvent.change(input, { target: { value: 'system:authenticated' } });

  expect(await screen.findByText('✗ not reachable')).toBeInTheDocument();
  expect(screen.getByText('none')).toBeInTheDocument();
});

test('shows no quota when the candidate group set matches no subscription', async () => {
  mockAll([modelX], [premiumSub], [authPolicy]);

  render(<AccessSimulatorTab />);

  const input = await screen.findByPlaceholderText(/system:authenticated/i);
  fireEvent.change(input, { target: { value: 'some-other-group' } });

  expect(await screen.findByText(/no quota for this group set/i)).toBeInTheDocument();
  expect(screen.getByText('✗ not reachable')).toBeInTheDocument();
});

test('shows an unavailable notice when models cannot be read', async () => {
  mockGetModels.mockResolvedValue({ available: false, reason: 'forbidden', items: [] });
  mockGetSubscriptions.mockResolvedValue({ available: true, reason: null, items: [] });
  mockGetAuthPolicies.mockResolvedValue({ available: true, reason: null, items: [] });

  render(<AccessSimulatorTab />);

  expect(await screen.findByText(/MaaS visibility unavailable/i)).toBeInTheDocument();
});
