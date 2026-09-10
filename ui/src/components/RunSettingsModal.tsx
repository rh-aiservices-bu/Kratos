import { useEffect, useState } from 'react';
import { Button, Modal, Spinner } from '@patternfly/react-core';
import { CodeEditor, Language } from '@patternfly/react-code-editor';
import '../monacoSetup';
import { getRunConfig } from '../api/client';

interface Props {
  runId: string;
  onClose: () => void;
}

export function RunSettingsModal({ runId, onClose }: Props) {
  const [yamlText, setYamlText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getRunConfig(runId).then((text) => {
      if (active) {
        setYamlText(text);
        setLoading(false);
      }
    });
    return () => {
      active = false;
    };
  }, [runId]);

  return (
    <Modal
      isOpen
      onClose={onClose}
      aria-label="Run settings"
      title="Run Settings"
      variant="large"
      actions={[
        <Button key="close" variant="link" onClick={onClose}>
          Close
        </Button>,
      ]}
    >
      {loading ? (
        <Spinner size="md" aria-label="Loading settings" />
      ) : yamlText ? (
        // Mirrors OpenShift console's own "View YAML" — same underlying
        // component family (PatternFly CodeEditor / Monaco), read-only here
        // since this is a record of what already ran, not an editable form.
        <CodeEditor
          isReadOnly
          isDarkTheme
          isCopyEnabled
          isDownloadEnabled
          isLineNumbersVisible
          language={Language.yaml}
          code={yamlText}
          height="480px"
          downloadFileName={`${runId}.yaml`}
          copyButtonToolTipText="Copy YAML"
          copyButtonSuccessTooltipText="Copied!"
        />
      ) : (
        <p style={{ color: '#888', fontStyle: 'italic' }}>
          Settings aren't available yet — the run may not have started.
        </p>
      )}
    </Modal>
  );
}
