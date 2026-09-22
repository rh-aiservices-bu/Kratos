import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { RunTrigger } from './RunTrigger';
import type { Scenario } from '../api/client';

function mockFetch(
  modelsResponse: unknown = { available: true, reason: null, items: [] },
  subscriptionsResponse: unknown = { available: true, reason: null, items: [] },
) {
  global.fetch = jest.fn((url: string) => {
    if (url === '/api/maas/models') {
      return Promise.resolve({
        ok: true,
        json: async () => modelsResponse,
      } as unknown as Response);
    }
    if (url === '/api/maas/subscriptions') {
      return Promise.resolve({
        ok: true,
        json: async () => subscriptionsResponse,
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

const subscriptionOnlyScenario: Scenario = {
  name: 'subscription_only',
  description: 'test',
  category: 'Load Testing',
  config: {
    subscription: '',
  },
};

const singleKeyLoadScenario: Scenario = {
  name: 'single_key_load',
  description: 'test',
  category: 'Load Testing',
  config: {
    request_count: 100,
    concurrency: 5,
    subscription: '',
    target_model_name: '',
    target_model_namespace: '',
  },
};

const modelA = {
  name: 'model-a',
  namespace: 'llm',
  display_name: 'Model A',
  ready: true,
  subscriptions: [{ name: 'sub-a', display_name: 'Sub A', description: '' }],
};
const modelB = {
  name: 'model-b',
  namespace: 'llm',
  display_name: 'Model B',
  ready: true,
  subscriptions: [{ name: 'sub-b', display_name: 'Sub B', description: '' }],
};
const subA = {
  name: 'sub-a',
  namespace: 'models-as-a-service',
  display_name: 'Sub A',
  priority: 100,
  ready: true,
  owner: { groups: ['system:authenticated'], users: [] },
  model_refs: [{ name: 'model-a', namespace: 'llm', token_rate_limits: [], display_name: 'Model A', model_exists: true, model_ready: true, has_auth_policy: true }],
};
const subB = {
  name: 'sub-b',
  namespace: 'models-as-a-service',
  display_name: 'Sub B',
  priority: 50,
  ready: true,
  owner: { groups: ['system:authenticated'], users: [] },
  model_refs: [{ name: 'model-b', namespace: 'llm', token_rate_limits: [], display_name: 'Model B', model_exists: true, model_ready: true, has_auth_policy: true }],
};

test('scenarios without target_model_name/namespace or subscription never fetch either endpoint', async () => {
  mockFetch();

  await act(async () => {
    render(<RunTrigger scenario={plainScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />);
  });

  expect(screen.getByLabelText('request_count')).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalledWith('/api/maas/models');
  expect(global.fetch).not.toHaveBeenCalledWith('/api/maas/subscriptions');
});

test('renders a model picker populated from /api/maas/models', async () => {
  mockFetch({
    available: true,
    reason: null,
    items: [
      { name: 'facebook-opt-125m-simulated', namespace: 'llm', display_name: 'Simulator', ready: true, subscriptions: [] },
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

test('renders a subscription picker populated from /api/maas/subscriptions, with no model fields to cross-filter', async () => {
  mockFetch(undefined, { available: true, reason: null, items: [subA, subB] });

  await act(async () => {
    render(
      <RunTrigger scenario={subscriptionOnlyScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
  });

  await waitFor(() => screen.getByLabelText('subscription'));

  const select = screen.getByLabelText('subscription') as HTMLSelectElement;
  expect(select.options).toHaveLength(3); // auto-select + sub-a + sub-b
  fireEvent.change(select, { target: { value: 'sub-a' } });
  expect(select.value).toBe('sub-a');
});

test('falls back to manual subscription field when subscriptions are unavailable', async () => {
  mockFetch(undefined, { available: false, reason: 'forbidden', items: [] });

  await act(async () => {
    render(
      <RunTrigger scenario={subscriptionOnlyScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
  });

  await waitFor(() => screen.getByLabelText('subscription'));

  const field = screen.getByLabelText('subscription');
  expect(field.tagName).toBe('INPUT');
  expect(screen.getByText(/couldn't load subscriptions/i)).toBeInTheDocument();
});

test('subscription and model pickers cross-filter each other', async () => {
  mockFetch(
    { available: true, reason: null, items: [modelA, modelB] },
    { available: true, reason: null, items: [subA, subB] },
  );

  await act(async () => {
    render(
      <RunTrigger scenario={singleKeyLoadScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
  });

  await waitFor(() => screen.getByLabelText('subscription'));
  const subSelect = screen.getByLabelText('subscription') as HTMLSelectElement;
  const modelSelect = screen.getByLabelText('target model') as HTMLSelectElement;

  // Before any selection, both pickers show everything.
  expect(subSelect.options).toHaveLength(3);
  expect(modelSelect.options).toHaveLength(3);

  // Picking sub-a narrows the model picker to model-a only (+ the placeholder).
  fireEvent.change(subSelect, { target: { value: 'sub-a' } });
  await waitFor(() => expect(modelSelect.options).toHaveLength(2));
  expect(screen.getByText(/showing models covered by the selected subscription/i)).toBeInTheDocument();

  // Reset, then pick model-b first — narrows the subscription picker to sub-b only.
  fireEvent.change(subSelect, { target: { value: '' } });
  await waitFor(() => expect(modelSelect.options).toHaveLength(3));
  fireEvent.change(modelSelect, { target: { value: 'llm/model-b' } });
  await waitFor(() => expect(subSelect.options).toHaveLength(2));
  expect(screen.getByText(/showing subscriptions available for the selected model/i)).toBeInTheDocument();
});

test('picking an incompatible model clears a subscription pin the fetched models could not confirm', async () => {
  // sub-c targets a model that never shows up in /api/maas/models (e.g. a
  // dangling modelRef) — narrowing would be empty, so the model picker falls
  // back to showing everything unfiltered, and remains genuinely selectable.
  const subC = { ...subA, name: 'sub-c', display_name: 'Sub C', model_refs: [{ ...subA.model_refs[0], name: 'model-zzz' }] };
  mockFetch(
    { available: true, reason: null, items: [modelA, modelB] },
    { available: true, reason: null, items: [subC] },
  );

  await act(async () => {
    render(
      <RunTrigger scenario={singleKeyLoadScenario} onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
  });

  await waitFor(() => screen.getByLabelText('subscription'));
  const subSelect = screen.getByLabelText('subscription') as HTMLSelectElement;
  const modelSelect = screen.getByLabelText('target model') as HTMLSelectElement;

  fireEvent.change(subSelect, { target: { value: 'sub-c' } });
  await waitFor(() =>
    expect(screen.getByText(/no known models for the selected subscription/i)).toBeInTheDocument(),
  );
  expect(modelSelect.options).toHaveLength(3); // fallback: unfiltered

  fireEvent.change(modelSelect, { target: { value: 'llm/model-a' } });
  await waitFor(() => expect(subSelect.value).toBe(''));
});
