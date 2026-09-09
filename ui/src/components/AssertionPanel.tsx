import type { AssertionState } from '../api/client';

interface Props {
  assertions: AssertionState[];
}

const ASSERTION_COLORS: Record<AssertionState['status'], string> = {
  PENDING: '#9e9e9e',
  PASSING: '#2e7d32',
  FAILING: '#c62828',
};

const ASSERTION_BG: Record<AssertionState['status'], string> = {
  PENDING: '#f5f5f5',
  PASSING: '#f1f8f1',
  FAILING: '#fdf3f3',
};

const STATUS_ICON: Record<AssertionState['status'], string> = {
  PENDING: '○',
  PASSING: '✓',
  FAILING: '✗',
};

function formatValue(v: number | null): string {
  if (v === null) return '—';
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}

function formatName(name: string): string {
  return name
    .replace(/_pct$/i, '_percent')
    .replace(/_ms$/i, ' (ms)')
    .replace(/_rps$/i, ' (rps)')
    .replace(/_percent$/i, ' (%)')
    .replace(/_/g, ' ')
    .replace(/\bp(\d+)\b/gi, 'P$1')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

export function AssertionPanel({ assertions }: Props) {
  if (assertions.length === 0) {
    return (
      <div>
        <p className="kratos-section-heading">Assertions</p>
        <p style={{ color: '#aaa', fontSize: '0.85rem', fontStyle: 'italic' }}>
          Waiting for assertion data…
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="kratos-section-heading">Assertions</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
        {assertions.map((a) => {
          const color = ASSERTION_COLORS[a.status];
          const bg = ASSERTION_BG[a.status];
          return (
            <div
              key={a.name}
              className="kratos-assertion-card"
              style={
                {
                  '--assertion-color': color,
                  '--assertion-bg': bg,
                } as React.CSSProperties
              }
            >
              <span className="kratos-assertion-card__name">{formatName(a.name)}</span>
              <span className="kratos-assertion-card__value">{formatValue(a.value)}</span>
              {a.expression && (
                <span className="kratos-assertion-card__expr">target: {a.expression}</span>
              )}
              <span className="kratos-assertion-card__status">
                <span>{STATUS_ICON[a.status]}</span>
                <span>{a.status}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
