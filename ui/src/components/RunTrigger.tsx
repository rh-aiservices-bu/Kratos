import { useState } from 'react';
import { Button, Modal } from '@patternfly/react-core';
import { createRun, type Scenario } from '../api/client';

interface Props {
  scenario: Scenario;
  onConfirm: (runId: string) => void;
  onCancel: () => void;
}

export function RunTrigger({ scenario, onConfirm, onCancel }: Props) {
  const [loading, setLoading] = useState(false);

  async function handleConfirm() {
    setLoading(true);
    try {
      const result = await createRun(scenario.name);
      onConfirm(result.run_id);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      isOpen
      onClose={onCancel}
      aria-label={`Run ${scenario.name}`}
      title={`Run scenario: ${scenario.name}`}
      variant="small"
      actions={[
        <Button
          key="confirm"
          variant="primary"
          onClick={() => void handleConfirm()}
          isLoading={loading}
          isDisabled={loading}
        >
          Confirm
        </Button>,
        <Button key="cancel" variant="link" onClick={onCancel} isDisabled={loading}>
          Cancel
        </Button>,
      ]}
    >
      <p>{scenario.description}</p>
      <p>Start a new run of this scenario?</p>
    </Modal>
  );
}
