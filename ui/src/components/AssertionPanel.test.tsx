import { render, screen } from '@testing-library/react';
import { AssertionPanel } from './AssertionPanel';
import type { AssertionState } from '../api/client';

test('shows placeholder when assertions list is empty', () => {
  render(<AssertionPanel assertions={[]} />);
  expect(screen.getByText(/waiting for assertion data/i)).toBeInTheDocument();
});

test('renders formatted assertion names and statuses', () => {
  const assertions: AssertionState[] = [
    { name: 'error_rate_pct', status: 'PASSING', value: 2.1, expression: '< 5' },
    { name: 'p99_latency_ms', status: 'PENDING', value: null },
    { name: 'throughput_rps', status: 'FAILING', value: 15 },
  ];

  render(<AssertionPanel assertions={assertions} />);

  expect(screen.getByText(/Error Rate/i)).toBeInTheDocument();
  expect(screen.getByText('PASSING')).toBeInTheDocument();
  expect(screen.getByText('PENDING')).toBeInTheDocument();
  expect(screen.getByText('FAILING')).toBeInTheDocument();
});
