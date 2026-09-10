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
  duration_ms?: number | null;
}

export interface AssertionState {
  task: string | null;
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

export async function stopRun(runId: string): Promise<void> {
  const r = await fetch(`/api/runs/${runId}/stop`, { method: 'POST' });
  if (!r.ok) throw new Error(`stopRun failed: ${r.status}`);
}

export interface TaskProgressEntry {
  name: string;
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAIL' | 'CANCELLED';
  progress?: { current: number; total: number };
  assertions_status?: 'PASSING' | 'FAILING' | 'PENDING';
  started_at?: string;
  duration_ms?: number;
}

export interface ProgressResponse {
  tasks: TaskProgressEntry[];
  run_started_at?: string;
}

export async function getProgress(runId: string): Promise<ProgressResponse> {
  try {
    const r = await fetch(`/api/runs/${runId}/progress`);
    if (!r.ok) return { tasks: [] };
    const data = (await r.json()) as ProgressResponse;
    return { tasks: data.tasks ?? [], run_started_at: data.run_started_at };
  } catch {
    return { tasks: [] };
  }
}

export async function getRunConfig(runId: string): Promise<string | null> {
  try {
    const r = await fetch(`/api/runs/${runId}/config`);
    if (!r.ok) return null;
    const data = (await r.json()) as { config_yaml: string | null };
    return data.config_yaml ?? null;
  } catch {
    return null;
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

