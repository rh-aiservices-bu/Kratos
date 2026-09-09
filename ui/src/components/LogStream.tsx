import { useEffect, useRef, useState } from 'react';
import { CodeBlock, CodeBlockCode } from '@patternfly/react-core';

type StreamStatus = 'connecting' | 'streaming' | 'completed' | 'error';

const STATUS_LABEL: Record<StreamStatus, string> = {
  connecting: 'Connecting',
  streaming: 'Streaming',
  completed: 'Completed',
  error: 'Error',
};

const POLL_INTERVAL_MS = 1000;

interface LogPollResponse {
  lines: string[];
  done: boolean;
  next_offset: number;
}

interface Props {
  runId: string;
}

export function LogStream({ runId }: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLines([]);
    setStatus('connecting');

    let active = true;
    let offset = 0;

    async function poll() {
      let consecutiveErrors = 0;
      while (active) {
        try {
          const res = await fetch(`/api/runs/${runId}/logs/lines?offset=${offset}`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);

          const data = (await res.json()) as LogPollResponse;
          consecutiveErrors = 0;

          if (data.lines.length > 0) {
            setStatus('streaming');
            setLines((prev) => [...prev, ...data.lines]);
            offset = data.next_offset;
          }

          if (data.done) {
            setStatus('completed');
            return;
          }
        } catch {
          consecutiveErrors++;
          if (consecutiveErrors >= 10) {
            setStatus('error');
            return;
          }
          // Transient error — keep retrying silently.
        }

        await new Promise<void>((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    }

    void poll();
    return () => {
      active = false;
    };
  }, [runId]);

  // Scroll within the log box only — never touch window scroll.
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
