import { render, screen } from '@testing-library/react';
import { LogStream } from './LogStream';
import * as client from '../api/client';

jest.mock('../api/client');

const mockOpenLogStream = client.openLogStream as jest.MockedFunction<typeof client.openLogStream>;

function makeFakeEventSource() {
  return {
    onmessage: null as ((ev: { data: string }) => void) | null,
    onerror: null as (() => void) | null,
    close: jest.fn(),
  };
}

test('renders waiting message initially', () => {
  const fakeEs = makeFakeEventSource();
  mockOpenLogStream.mockReturnValue(fakeEs as unknown as EventSource);

  render(<LogStream runId="run-1" onAssertionUpdate={() => undefined} />);

  expect(screen.getByText(/waiting for logs/i)).toBeInTheDocument();
});
