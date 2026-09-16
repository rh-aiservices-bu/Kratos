import { fireEvent, render, screen } from '@testing-library/react';
import { ModelsTab } from './ModelsTab';
import * as client from '../../api/client';
import type { MaasModel } from '../../api/client';

jest.mock('../../api/client');

jest.mock('../RawYamlModal', () => ({
  RawYamlModal: ({ title, yamlText }: { title: string; yamlText: string | null }) => (
    <div data-testid="raw-yaml-modal">
      <span>{title}</span>
      <pre>{yamlText}</pre>
    </div>
  ),
}));

const mockGetModels = client.getMaasModels as jest.MockedFunction<typeof client.getMaasModels>;

const baseModel: MaasModel = {
  name: 'facebook-opt-125m-simulated',
  namespace: 'llm',
  display_name: 'Facebook OPT 125M (Simulated)',
  description: 'CPU-only simulator for testing MaaS without a real LLM',
  kind: 'LLMInferenceService',
  hosting: 'internal',
  backing_name: 'facebook-opt-125m-simulated',
  phase: 'Ready',
  ready: true,
  endpoint: 'https://maas.example.com/llm/facebook-opt-125m-simulated',
  subscriptions: [
    { name: 'simulator-free', display_name: 'Simulator Free Tier', description: null },
  ],
  has_auth_policy: true,
  gateway_access_label: true,
  serving: { replicas: 1, resources: null, conditions: [] },
  raw: {},
  raw_yaml: 'maasModelRef:\n  kind: MaaSModelRef\n',
};

test('shows an unavailable notice when the SA lacks RBAC', async () => {
  mockGetModels.mockResolvedValue({ available: false, reason: 'forbidden', items: [] });

  render(<ModelsTab />);

  expect(await screen.findByText(/MaaS visibility unavailable/i)).toBeInTheDocument();
});

test('renders model rows with hosting, status, endpoint, and subscriptions', async () => {
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [baseModel] });

  render(<ModelsTab />);

  expect(await screen.findByText('Facebook OPT 125M (Simulated)')).toBeInTheDocument();
  expect(screen.getByText('Internal')).toBeInTheDocument();
  expect(screen.getByText('llm')).toBeInTheDocument();
  expect(screen.getByText('LLMInferenceService')).toBeInTheDocument();
  expect(screen.getByText('Ready')).toBeInTheDocument();
  expect(screen.getByText('https://maas.example.com/llm/facebook-opt-125m-simulated')).toBeInTheDocument();
  expect(screen.getByText('Simulator Free Tier')).toBeInTheDocument();
  expect(screen.getByText('1 replica')).toBeInTheDocument();
  expect(screen.getByText('Namespace')).toBeInTheDocument();
  expect(screen.getByText('✓ gateway-access')).toBeInTheDocument();
  expect(screen.getByText('✓ has auth policy')).toBeInTheDocument();
});

test('flags a namespace missing the gateway-access label', async () => {
  const noLabel: MaasModel = { ...baseModel, gateway_access_label: false };
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [noLabel] });

  render(<ModelsTab />);

  expect(await screen.findByText('⚠ missing gateway-access label')).toBeInTheDocument();
});

test('flags a model with no matching auth policy', async () => {
  const noAuthPolicy: MaasModel = { ...baseModel, has_auth_policy: false };
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [noAuthPolicy] });

  render(<ModelsTab />);

  expect(await screen.findByText('⚠ no auth policy')).toBeInTheDocument();
});

test('shows unknown (not a false negative) when auth-policy/label state cannot be read', async () => {
  const unknown: MaasModel = { ...baseModel, has_auth_policy: null, gateway_access_label: null };
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [unknown] });

  render(<ModelsTab />);

  expect(await screen.findByText('Auth policy: unknown')).toBeInTheDocument();
  expect(screen.queryByText('⚠ missing gateway-access label')).not.toBeInTheDocument();
  expect(screen.queryByText('✓ gateway-access')).not.toBeInTheDocument();
});

test('shows an External badge for externally-hosted models', async () => {
  const external: MaasModel = {
    ...baseModel,
    name: 'gpt-4o-proxy',
    display_name: 'GPT-4o (external)',
    kind: 'ExternalModel',
    hosting: 'external',
    serving: null,
  };
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [external] });

  render(<ModelsTab />);

  expect(await screen.findByText('External')).toBeInTheDocument();
  expect(screen.getByText('ExternalModel')).toBeInTheDocument();
});

test('shows an empty-state message when there are no models', async () => {
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [] });

  render(<ModelsTab />);

  expect(await screen.findByText(/no models found/i)).toBeInTheDocument();
});

test('clicking View YAML opens the raw YAML modal for that model', async () => {
  mockGetModels.mockResolvedValue({ available: true, reason: null, items: [baseModel] });

  render(<ModelsTab />);

  fireEvent.click(await screen.findByRole('button', { name: /view yaml/i }));

  // The modal is lazy-loaded (Suspense) so it doesn't ship Monaco in the main
  // bundle — see ModelsTab.tsx — so it only appears after a tick.
  const modal = await screen.findByTestId('raw-yaml-modal');
  expect(modal).toHaveTextContent('Model: Facebook OPT 125M (Simulated)');
  expect(modal).toHaveTextContent('kind: MaaSModelRef');
});
