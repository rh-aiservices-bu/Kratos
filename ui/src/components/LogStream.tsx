import { useEffect, useRef, useState } from 'react';
import { CodeBlock, CodeBlockCode } from '@patternfly/react-core';
import { openLogStream } from '../api/client';

export interface AssertionState {
  name: string;
  status: 'PENDING' | 'PASSING' | 'FAILING';
  value: number | null;
}

interface Props {
  runId: string;
  onAssertionUpdate: (assertions: AssertionState[]) => void;
}

export function LogStream({ runId, onAssertionUpdate }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLines([]);
    const es = openLogStream(runId);

    es.onmessage = (ev) => {
      const raw: string = ev.data;
      try {
        const parsed = JSON.parse(raw) as { event?: string; data?: AssertionState[] };
        if (parsed.event === 'assertion_state' && Array.isArray(parsed.data)) {
          onAssertionUpdate(parsed.data);
          return;
        }
      } catch {
        // not JSON — treat as a plain log line
      }
      setLines((prev) => [...prev, raw]);
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, [runId, onAssertionUpdate]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [lines]);

  return (
    <CodeBlock style={{ maxHeight: '400px', overflowY: 'auto' }}>
      <CodeBlockCode>{lines.join('\n') || '(waiting for logs…)'}</CodeBlockCode>
      <div ref={bottomRef} />
    </CodeBlock>
  );
}
