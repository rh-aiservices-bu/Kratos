import { render, screen } from '@testing-library/react';
import { ScenarioList } from './ScenarioList';
import * as client from '../api/client';

jest.mock('../api/client');

const mockListScenarios = client.listScenarios as jest.MockedFunction<typeof client.listScenarios>;

test('renders a Run button for each scenario', async () => {
  mockListScenarios.mockResolvedValue([
    { name: 'single_key_load', description: 'Baseline load test' },
    { name: 'direct_inference', description: 'Direct inference test' },
  ]);

  render(<ScenarioList onRun={() => undefined} />);

  expect(await screen.findByText('single_key_load')).toBeInTheDocument();
  expect(screen.getByText('direct_inference')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /run/i })).toHaveLength(2);
});

test('renders empty state when no scenarios are returned', async () => {
  mockListScenarios.mockResolvedValue([]);

  render(<ScenarioList onRun={() => undefined} />);

  expect(await screen.findByText(/no scenarios available/i)).toBeInTheDocument();
});
