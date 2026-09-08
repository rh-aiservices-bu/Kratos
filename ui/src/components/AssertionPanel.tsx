import { Label, Stack, StackItem, Title } from '@patternfly/react-core';
import type { AssertionState } from './LogStream';

interface Props {
  assertions: AssertionState[];
}

const STATUS_COLOR: Record<AssertionState['status'], 'blue' | 'green' | 'red'> = {
  PENDING: 'blue',
  PASSING: 'green',
  FAILING: 'red',
};

export function AssertionPanel({ assertions }: Props) {
  if (assertions.length === 0) return null;

  return (
    <div>
      <Title headingLevel="h3" size="md">
        Assertions
      </Title>
      <Stack hasGutter>
        {assertions.map((a) => (
          <StackItem key={a.name}>
            <Label color={STATUS_COLOR[a.status]}>
              {a.name}: {a.status}
              {a.value !== null ? ` (${a.value})` : ''}
            </Label>
          </StackItem>
        ))}
      </Stack>
    </div>
  );
}
