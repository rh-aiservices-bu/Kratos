export interface Scenario {
  name: string;
  description: string;
  config: Record<string, string | number | boolean>;
}

export interface Run {
  id: string;
  scenario: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface AssertionState {
  name: string;
  status: 'PENDING' | 'PASSING' | 'FAILING';
  value: number | null;
  expected_value?: number | null;
  expression?: string;
}

export interface CreateRunResponse {
  run_id: string;
  scenario: string;
  status: string;
}

export async function listScenarios(): Promise<Scenario[]> {
  const r = await fetch('/api/scenarios');
  if (!r.ok) throw new Error(`listScenarios failed: ${r.status}`);
  return r.json() as Promise<Scenario[]>;
}

export async function createRun(
  scenario: string,
  config_overrides: Record<string, string | number> = {},
): Promise<CreateRunResponse> {
  const r = await fetch('/api/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario, config_overrides }),
  });
  if (!r.ok) throw new Error(`createRun failed: ${r.status}`);
  return r.json() as Promise<CreateRunResponse>;
}

export async function listRuns(): Promise<Run[]> {
  const r = await fetch('/api/runs');
  if (!r.ok) throw new Error(`listRuns failed: ${r.status}`);
  return r.json() as Promise<Run[]>;
}

export async function getRun(runId: string): Promise<Run> {
  const r = await fetch(`/api/runs/${runId}`);
  if (!r.ok) throw new Error(`getRun failed: ${r.status}`);
  return r.json() as Promise<Run>;
}

export interface TaskProgressEntry {
  name: string;
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAIL';
  progress?: { current: number; total: number };
}

export async function getProgress(runId: string): Promise<TaskProgressEntry[]> {
  try {
    const r = await fetch(`/api/runs/${runId}/progress`);
    if (!r.ok) return [];
    const data = (await r.json()) as { tasks: TaskProgressEntry[] };
    return data.tasks ?? [];
  } catch {
    return [];
  }
}

export async function getAssertions(runId: string): Promise<AssertionState[]> {
  try {
    const r = await fetch(`/api/runs/${runId}/assertions`);
    if (!r.ok) return [];
    const data = (await r.json()) as { assertions: AssertionState[] };
    return data.assertions ?? [];
  } catch {
    return [];
  }
}

