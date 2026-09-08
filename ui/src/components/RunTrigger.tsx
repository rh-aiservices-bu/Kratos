import { useState } from 'react';
import { Button, Modal, ModalBody, ModalFooter, ModalHeader } from '@patternfly/react-core';
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
    <Modal isOpen aria-label={`Run ${scenario.name}`} onClose={onCancel} variant="small">
      <ModalHeader title={`Run scenario: ${scenario.name}`} />
      <ModalBody>
        <p>{scenario.description}</p>
        <p>Start a new run of this scenario?</p>
      </ModalBody>
      <ModalFooter>
        <Button variant="primary" onClick={() => void handleConfirm()} isLoading={loading} isDisabled={loading}>
          Confirm
        </Button>
        <Button variant="link" onClick={onCancel} isDisabled={loading}>
          Cancel
        </Button>
      </ModalFooter>
    </Modal>
  );
}
