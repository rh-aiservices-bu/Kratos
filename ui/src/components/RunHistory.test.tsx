import { render, screen } from '@testing-library/react';
import { RunHistory } from './RunHistory';
import * as client from '../api/client';

jest.mock('../api/client');

const mockListRuns = client.listRuns as jest.MockedFunction<typeof client.listRuns>;

test('renders run rows', async () => {
  mockListRuns.mockResolvedValue([
    {
      id: 'abc12345-0000-0000-0000-000000000000',
      scenario: 'single_key_load',
      status: 'PASS',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:01:00Z',
    },
  ]);

  render(<RunHistory />);

  expect(await screen.findByText('single_key_load')).toBeInTheDocument();
  expect(screen.getByText('PASS')).toBeInTheDocument();
});

test('renders empty message when no runs', async () => {
  mockListRuns.mockResolvedValue([]);

  render(<RunHistory />);

  expect(await screen.findByText(/no runs yet/i)).toBeInTheDocument();
});
