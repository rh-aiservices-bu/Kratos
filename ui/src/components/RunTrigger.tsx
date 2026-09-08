import { useState } from 'react';
import { Button, Modal } from '@patternfly/react-core';
import { createRun, type Scenario } from '../api/client';

interface Props {
  scenario: Scenario;
  onConfirm: (runId: string) => void;
  onCancel: () => void;
}

type ConfigValues = Record<string, string | number>;

function initValues(config: Scenario['config']): ConfigValues {
  const out: ConfigValues = {};
  for (const [k, v] of Object.entries(config)) {
    out[k] = v as string | number;
  }
  return out;
}

export function RunTrigger({ scenario, onConfirm, onCancel }: Props) {
  const [loading, setLoading] = useState(false);
  const [values, setValues] = useState<ConfigValues>(() => initValues(scenario.config));

  function handleChange(key: string, raw: string, isNumber: boolean) {
    setValues((prev) => ({
      ...prev,
      [key]: isNumber ? (raw === '' ? 0 : Number(raw)) : raw,
    }));
  }

  async function handleConfirm() {
    setLoading(true);
    try {
      const result = await createRun(scenario.name, values);
      onConfirm(result.run_id);
    } finally {
      setLoading(false);
    }
  }

  const hasConfig = Object.keys(scenario.config).length > 0;

  return (
    <Modal
      isOpen
      onClose={onCancel}
      aria-label={`Run ${scenario.name}`}
      title={`Run: ${scenario.name.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}`}
      variant="medium"
      actions={[
        <Button
          key="confirm"
          variant="primary"
          onClick={() => void handleConfirm()}
          isLoading={loading}
          isDisabled={loading}
        >
          Launch Run
        </Button>,
        <Button key="cancel" variant="link" onClick={onCancel} isDisabled={loading}>
          Cancel
        </Button>,
      ]}
    >
      <p style={{ color: '#555', marginBottom: hasConfig ? '1.25rem' : 0 }}>
        {scenario.description}
      </p>

      {hasConfig && (
        <>
          <p className="kratos-section-heading" style={{ marginBottom: '0.75rem' }}>
            Configuration
          </p>
          <div className="kratos-config-form">
            {Object.entries(scenario.config).map(([key, defaultVal]) => {
              const isNumber = typeof defaultVal === 'number';
              const current = values[key];
              return (
                <div key={key} className="kratos-config-form__field">
                  <label className="kratos-config-form__label" htmlFor={`cfg-${key}`}>
                    {key}
                  </label>
                  <input
                    id={`cfg-${key}`}
                    type={isNumber ? 'number' : 'text'}
                    value={current ?? ''}
                    onChange={(e) => handleChange(key, e.target.value, isNumber)}
                    style={{
                      padding: '0.375rem 0.5rem',
                      border: '1px solid #ccc',
                      borderRadius: '4px',
                      fontFamily: 'inherit',
                      fontSize: '0.875rem',
                    }}
                  />
                </div>
              );
            })}
          </div>
        </>
      )}
    </Modal>
  );
}
