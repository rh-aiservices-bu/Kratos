import { useEffect, useState } from 'react';
import { Button, Modal } from '@patternfly/react-core';
import { createRun, getMaasModels, type MaasModel, type Scenario } from '../api/client';

interface Props {
  scenario: Scenario;
  onConfirm: (runId: string) => void;
  onCancel: () => void;
}

type ConfigValues = Record<string, string | number>;

// Fields a MaaSModelRef-backed scenario (rate_limit_validation,
// access_denied_no_policy) uses to target a specific model CR — these two
// always travel together, so they get one combined picker instead of two
// blank text boxes the user has to copy exact CR names/namespaces into by
// hand (previously required an `oc get maasmodelrefs -A` first).
const _MODEL_NAME_KEY = 'target_model_name';
const _MODEL_NAMESPACE_KEY = 'target_model_namespace';

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

  const needsModelPicker =
    _MODEL_NAME_KEY in scenario.config && _MODEL_NAMESPACE_KEY in scenario.config;
  const [models, setModels] = useState<MaasModel[] | null>(null);
  const [modelsUnavailable, setModelsUnavailable] = useState(false);

  useEffect(() => {
    if (!needsModelPicker) return;
    let cancelled = false;
    void getMaasModels().then((res) => {
      if (cancelled) return;
      if (res.available) setModels(res.items);
      else setModelsUnavailable(true);
    });
    return () => {
      cancelled = true;
    };
  }, [needsModelPicker]);

  function handleChange(key: string, raw: string, isNumber: boolean) {
    setValues((prev) => ({
      ...prev,
      [key]: isNumber ? (raw === '' ? 0 : Number(raw)) : raw,
    }));
  }

  function handleModelSelect(name: string, namespace: string) {
    setValues((prev) => ({
      ...prev,
      [_MODEL_NAME_KEY]: name,
      [_MODEL_NAMESPACE_KEY]: namespace,
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
              const showingPicker = needsModelPicker && !!models && models.length > 0;

              // target_model_namespace is set together with target_model_name
              // by the picker below — no separate field for it. Only hidden
              // once the picker is actually rendering; if models never load
              // (RBAC/network issue) or the list comes back empty, this stays
              // a normal manual field alongside target_model_name's fallback.
              if (key === _MODEL_NAMESPACE_KEY && showingPicker) return null;

              if (key === _MODEL_NAME_KEY && showingPicker) {
                const currentName = String(values[_MODEL_NAME_KEY] ?? '');
                const currentNamespace = String(values[_MODEL_NAMESPACE_KEY] ?? '');
                const currentKey =
                  currentName && currentNamespace ? `${currentNamespace}/${currentName}` : '';
                return (
                  <div key={key} className="kratos-config-form__field">
                    <label className="kratos-config-form__label" htmlFor="cfg-target_model">
                      target model
                    </label>
                    <select
                      id="cfg-target_model"
                      value={currentKey}
                      onChange={(e) => {
                        const [namespace, name] = e.target.value.split('/');
                        if (name && namespace) handleModelSelect(name, namespace);
                      }}
                      style={{
                        padding: '0.375rem 0.5rem',
                        border: '1px solid #ccc',
                        borderRadius: '4px',
                        fontFamily: 'inherit',
                        fontSize: '0.875rem',
                      }}
                    >
                      <option value="">Select a model exposed through MaaS…</option>
                      {models.map((m) => (
                        <option key={`${m.namespace}/${m.name}`} value={`${m.namespace}/${m.name}`}>
                          {m.display_name} ({m.namespace}/{m.name}){m.ready ? '' : ' — not ready'}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              }

              // Fallback: plain text inputs — used for every other field, and
              // for target_model_name/target_model_namespace too when the
              // MaaS Setup models list isn't available (RBAC/network issue)
              // or came back empty, so the scenario stays usable by hand.
              if (key === _MODEL_NAME_KEY && needsModelPicker && modelsUnavailable) {
                return (
                  <div key={key} className="kratos-config-form__field">
                    <label className="kratos-config-form__label" htmlFor={`cfg-${key}`}>
                      {key}
                    </label>
                    <input
                      id={`cfg-${key}`}
                      type="text"
                      value={values[key] ?? ''}
                      onChange={(e) => handleChange(key, e.target.value, false)}
                      style={{
                        padding: '0.375rem 0.5rem',
                        border: '1px solid #ccc',
                        borderRadius: '4px',
                        fontFamily: 'inherit',
                        fontSize: '0.875rem',
                      }}
                    />
                    <p style={{ color: '#888', fontSize: '0.75rem', margin: '0.25rem 0 0' }}>
                      Couldn&apos;t load models from MaaS Setup — enter the MaaSModelRef name
                      manually (and its namespace below).
                    </p>
                  </div>
                );
              }

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
