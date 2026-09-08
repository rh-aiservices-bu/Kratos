import { useEffect, useRef, useState } from 'react';
import { CodeBlock, CodeBlockCode } from '@patternfly/react-core';
import { openLogStream } from '../api/client';

export interface AssertionState {
  name: string;
  status: 'PENDING' | 'PASSING' | 'FAILING';
  value: number | null;
  expression?: string;
}

type StreamStatus = 'connecting' | 'streaming' | 'completed' | 'error';

const STATUS_LABEL: Record<StreamStatus, string> = {
  connecting: 'Connecting',
  streaming: 'Streaming',
  completed: 'Completed',
  error: 'Error',
};

interface Props {
  runId: string;
  onAssertionUpdate: (assertions: AssertionState[]) => void;
}

export function LogStream({ runId, onAssertionUpdate }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLines([]);
    setStatus('connecting');
    const es = openLogStream(runId);

    es.onopen = () => setStatus('streaming');

    es.onmessage = (ev) => {
      const raw: string = ev.data;
      try {
        const parsed = JSON.parse(raw) as { event?: string; data?: AssertionState[] };
        if (parsed.event === 'assertion_state' && Array.isArray(parsed.data)) {
          onAssertionUpdate(parsed.data);
          return;
        }
        if (parsed.event === 'done') {
          setStatus('completed');
          return;
        }
      } catch {
        // not JSON — plain log line
      }
      setStatus((prev) => (prev === 'connecting' ? 'streaming' : prev));
      setLines((prev) => [...prev, raw]);
    };

    es.onerror = () => {
      es.close();
      setStatus((prev) => (prev === 'streaming' ? 'completed' : 'error'));
    };

    return () => { es.close(); };
  }, [runId, onAssertionUpdate]);

  // Scroll within the container only — never touch window scroll position.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="kratos-log-block">
      <div className={`kratos-stream-status kratos-stream-status--${status}`}>
        <span className="kratos-stream-status__dot" />
        <span>{STATUS_LABEL[status]}</span>
        {lines.length > 0 && (
          <span style={{ marginLeft: 'auto', fontWeight: 400, fontSize: '0.75rem', color: '#888' }}>
            {lines.length} lines
          </span>
        )}
      </div>
      <div ref={scrollRef} style={{ maxHeight: '420px', overflowY: 'auto' }}>
        <CodeBlock>
          <CodeBlockCode>{lines.join('\n') || '(waiting for logs…)'}</CodeBlockCode>
        </CodeBlock>
      </div>
    </div>
  );
}
