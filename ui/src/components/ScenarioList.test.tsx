import { render, screen } from '@testing-library/react';
import { ScenarioList } from './ScenarioList';
import * as client from '../api/client';

jest.mock('../api/client');

const mockListScenarios = client.listScenarios as jest.MockedFunction<typeof client.listScenarios>;

test('renders a Run button for each scenario, grouped by category', async () => {
  mockListScenarios.mockResolvedValue([
    { name: 'single_key_load', description: 'Baseline load test', config: {}, category: 'Load Testing' },
    { name: 'direct_inference', description: 'Direct inference test', config: {}, category: 'Load Testing' },
    { name: 'rate_limit_validation', description: 'Rate limit test', config: {}, category: 'Rate Limiting' },
  ]);

  render(<ScenarioList onRun={() => undefined} />);

  // Component title-cases the underscore name for display, not the raw name.
  expect(await screen.findByText('Single Key Load')).toBeInTheDocument();
  expect(screen.getByText('Direct Inference')).toBeInTheDocument();
  expect(screen.getByText('Rate Limit Validation')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /run/i })).toHaveLength(3);

  // Category section headings.
  expect(screen.getByText('Load Testing')).toBeInTheDocument();
  expect(screen.getByText('Rate Limiting')).toBeInTheDocument();
});

test('always shows an empty Custom section when no scenario uses it', async () => {
  mockListScenarios.mockResolvedValue([
    { name: 'single_key_load', description: 'Baseline load test', config: {}, category: 'Load Testing' },
  ]);

  render(<ScenarioList onRun={() => undefined} />);

  await screen.findByText('Single Key Load');
  expect(screen.getByText('Custom')).toBeInTheDocument();
  expect(screen.getByText(/no custom scenarios yet/i)).toBeInTheDocument();
});

test('a scenario with an unrecognized category falls into Custom', async () => {
  mockListScenarios.mockResolvedValue([
    { name: 'my_scenario', description: 'A user-authored scenario', config: {}, category: 'Custom' },
  ]);

  render(<ScenarioList onRun={() => undefined} />);

  await screen.findByText('My Scenario');
  expect(screen.queryByText(/no custom scenarios yet/i)).not.toBeInTheDocument();
});

test('renders empty state when no scenarios are returned', async () => {
  mockListScenarios.mockResolvedValue([]);

  render(<ScenarioList onRun={() => undefined} />);

  expect(await screen.findByText(/no scenarios available/i)).toBeInTheDocument();
});
