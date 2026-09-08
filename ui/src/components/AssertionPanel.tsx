import type { AssertionState } from './LogStream';

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

export function AssertionPanel({ assertions }: Props) {
  if (assertions.length === 0) return null;

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
              <span className="kratos-assertion-card__name">{a.name}</span>
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
