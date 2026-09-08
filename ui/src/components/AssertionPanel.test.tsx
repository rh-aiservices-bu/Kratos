import { render, screen } from '@testing-library/react';
import { AssertionPanel } from './AssertionPanel';
import type { AssertionState } from './LogStream';

test('renders nothing when assertions list is empty', () => {
  const { container } = render(<AssertionPanel assertions={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test('renders assertion labels', () => {
  const assertions: AssertionState[] = [
    { name: 'error_rate_pct', status: 'PASSING', value: 2.1 },
    { name: 'p99_latency_ms', status: 'PENDING', value: null },
    { name: 'throughput_rps', status: 'FAILING', value: 15 },
  ];

  render(<AssertionPanel assertions={assertions} />);

  expect(screen.getByText(/error_rate_pct.*PASSING/)).toBeInTheDocument();
  expect(screen.getByText(/p99_latency_ms.*PENDING/)).toBeInTheDocument();
  expect(screen.getByText(/throughput_rps.*FAILING/)).toBeInTheDocument();
});
