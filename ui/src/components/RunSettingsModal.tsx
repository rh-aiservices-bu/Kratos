import { useEffect, useState } from 'react';
import { Button, CodeBlock, CodeBlockCode, Modal, Spinner } from '@patternfly/react-core';
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
      variant="medium"
      actions={[
        <Button key="close" variant="link" onClick={onClose}>
          Close
        </Button>,
      ]}
    >
      {loading ? (
        <Spinner size="md" aria-label="Loading settings" />
      ) : yamlText ? (
        <CodeBlock>
          <CodeBlockCode>{yamlText}</CodeBlockCode>
        </CodeBlock>
      ) : (
        <p style={{ color: '#888', fontStyle: 'italic' }}>
          Settings aren't available yet — the run may not have started.
        </p>
      )}
    </Modal>
  );
}
