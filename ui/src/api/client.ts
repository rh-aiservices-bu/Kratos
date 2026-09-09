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

