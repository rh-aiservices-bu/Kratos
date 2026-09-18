import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { RunTrigger } from './RunTrigger';
import type { Scenario } from '../api/client';

function mockFetch(modelsResponse: unknown) {
  global.fetch = jest.fn((url: string) => {
    if (url === '/api/maas/models') {
      return Promise.resolve({
        ok: true,
        json: async () => modelsResponse,
      } as unknown as Response);
    }
    return Promise.resolve({
      ok: true,
      json: async () => ({ run_id: 'run-1' }),
    } as unknown as Response);
  }) as unknown as typeof fetch;
}

afterEach(() => {
  jest.restoreAllMocks();
});

const rateLimitScenario: Scenario = {
  name: 'rate_limit_validation',
  description: 'test',
  category: 'Rate Limiting',
  config: {
    target_model_name: '',
    target_model_namespace: '',
    token_limit: 50,
  },
};

const plainScenario: Scenario = {
  name: 'single_key_load',
  description: 'test',
  category: 'Load Testing',
  config: {
    request_count: 100,
    concurrency: 5,
  },
};

test('scenarios without target_model_name/namespace never fetch MaaS models', async () => {
  mockFetch({ available: true, reason: null, items: [] });

  await act(async () => {
    render(<RunTrigger scenario={plainScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />);
  });

  expect(screen.getByLabelText('request_count')).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalledWith('/api/maas/models');
});

test('renders a model picker populated from /api/maas/models', async () => {
  mockFetch({
    available: true,
    reason: null,
    items: [
      { name: 'facebook-opt-125m-simulated', namespace: 'llm', display_name: 'Simulator', ready: true },
    ],
  });

  await act(async () => {
    render(
      <RunTrigger scenario={rateLimitScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
  });

  await waitFor(() => screen.getByLabelText('target model'));

  // Underlying raw fields are no longer shown once the picker is active.
  expect(screen.queryByLabelText('target_model_name')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('target_model_namespace')).not.toBeInTheDocument();

  const select = screen.getByLabelText('target model') as HTMLSelectElement;
  fireEvent.change(select, { target: { value: 'llm/facebook-opt-125m-simulated' } });
  expect(select.value).toBe('llm/facebook-opt-125m-simulated');
});

test('falls back to manual name/namespace fields when models are unavailable', async () => {
  mockFetch({ available: false, reason: 'forbidden', items: [] });

  await act(async () => {
    render(
      <RunTrigger scenario={rateLimitScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
  });

  await waitFor(() => screen.getByLabelText('target_model_name'));

  expect(screen.getByLabelText('target_model_name')).toBeInTheDocument();
  expect(screen.getByLabelText('target_model_namespace')).toBeInTheDocument();
  expect(screen.getByText(/couldn't load models/i)).toBeInTheDocument();
});
