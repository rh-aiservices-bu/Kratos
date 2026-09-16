import { fireEvent, render, screen } from '@testing-library/react';
import { SubscriptionsTab } from './SubscriptionsTab';
import * as client from '../../api/client';
import type { MaasSubscription } from '../../api/client';

jest.mock('../../api/client');

// Monaco/CodeEditor isn't testable in jsdom (no ResizeObserver/workers) and
// isn't exercised anywhere else in this test suite either — stub it so these
// tests verify SubscriptionsTab opens it with the right content, not Monaco itself.
jest.mock('../RawYamlModal', () => ({
  RawYamlModal: ({ title, yamlText }: { title: string; yamlText: string | null }) => (
    <div data-testid="raw-yaml-modal">
      <span>{title}</span>
      <pre>{yamlText}</pre>
    </div>
  ),
}));

const mockGetSubscriptions = client.getMaasSubscriptions as jest.MockedFunction<
  typeof client.getMaasSubscriptions
>;

const baseSubscription: MaasSubscription = {
  name: 'simulator-free',
  namespace: 'models-as-a-service',
  display_name: 'Simulator Free Tier',
  description: 'Free tier: 100 tokens/min for all authenticated users',
  priority: 10,
  owner: { groups: ['system:authenticated'], users: [] },
  models: [
    {
      name: 'facebook-opt-125m-simulated',
      namespace: 'llm',
      token_rate_limits: [{ limit: 100, window: '1m' }],
    },
  ],
  phase: 'Active',
  ready: true,
  priority_conflict: false,
  raw: {},
  raw_yaml: 'apiVersion: maas.opendatahub.io/v1alpha1\nkind: MaaSSubscription\n',
};

test('shows an unavailable notice when the SA lacks RBAC', async () => {
  mockGetSubscriptions.mockResolvedValue({ available: false, reason: 'forbidden', items: [] });

  render(<SubscriptionsTab />);

  expect(await screen.findByText(/MaaS visibility unavailable/i)).toBeInTheDocument();
  expect(screen.getByText(/rbac-maas-readonly.yaml/i)).toBeInTheDocument();
});

test('renders subscription rows with priority, phase, and rate limits', async () => {
  mockGetSubscriptions.mockResolvedValue({ available: true, reason: null, items: [baseSubscription] });

  render(<SubscriptionsTab />);

  expect(await screen.findByText('Simulator Free Tier')).toBeInTheDocument();
  expect(screen.getByText('10')).toBeInTheDocument();
  expect(screen.getByText('Active')).toBeInTheDocument();
  expect(screen.getByText('facebook-opt-125m-simulated')).toBeInTheDocument();
  expect(screen.getByText('100 / 1m')).toBeInTheDocument();
  expect(screen.getByText('system:authenticated')).toBeInTheDocument();
});

test('flags a priority conflict', async () => {
  const conflicting = { ...baseSubscription, priority_conflict: true };
  mockGetSubscriptions.mockResolvedValue({ available: true, reason: null, items: [conflicting] });

  render(<SubscriptionsTab />);

  expect(await screen.findByText(/priority conflict/i)).toBeInTheDocument();
});

test('shows an empty-state message when there are no subscriptions', async () => {
  mockGetSubscriptions.mockResolvedValue({ available: true, reason: null, items: [] });

  render(<SubscriptionsTab />);

  expect(await screen.findByText(/no subscriptions found/i)).toBeInTheDocument();
});

test('clicking View YAML opens the raw YAML modal for that subscription', async () => {
  mockGetSubscriptions.mockResolvedValue({ available: true, reason: null, items: [baseSubscription] });

  render(<SubscriptionsTab />);

  fireEvent.click(await screen.findByRole('button', { name: /view yaml/i }));

  // The modal is lazy-loaded (Suspense) so it doesn't ship Monaco in the main
  // bundle — see SubscriptionsTab.tsx — so it only appears after a tick.
  const modal = await screen.findByTestId('raw-yaml-modal');
  expect(modal).toHaveTextContent('Subscription: Simulator Free Tier');
  expect(modal).toHaveTextContent('kind: MaaSSubscription');
});
