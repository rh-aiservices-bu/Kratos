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

// ---------------------------------------------------------------------------
// MaaS Setup — live cluster visibility (see ADR-017 /
// docs/architecture/maas-domain-reference.md). Every endpoint here degrades
// to { available: false, reason } instead of a 4xx/5xx when the SA lacks
// RBAC for a given CRD or it isn't installed on this cluster — callers
// should render an unavailable notice for that reason, not treat it as an error.
// ---------------------------------------------------------------------------

export interface MaasTokenRateLimit {
  limit: number;
  window: string;
}

export interface MaasSubscription {
  name: string;
  namespace: string;
  display_name: string;
  description: string;
  priority: number | null;
  owner: { groups: string[]; users: string[] };
  models: { name: string; namespace: string; token_rate_limits: MaasTokenRateLimit[] }[];
  phase: string | null;
  ready: boolean;
  priority_conflict: boolean;
  raw: unknown;
  raw_yaml: string;
}

export interface MaasModelSubscriptionRef {
  name: string;
  display_name: string | null;
  description: string | null;
}

export interface MaasServingInfo {
  replicas: number | null;
  resources: unknown;
  conditions: { type: string; status: string }[];
}

export interface MaasExternalProviderRef {
  provider_name: string | null;
  target_model: string | null;
  api_format: string | null;
  path: string | null;
  endpoint: string | null;
  credential_secret_name: string | null;
  // null means "couldn't read the secret" — never collapse into false.
  credential_secret_label_ok: boolean | null;
}

export interface MaasModel {
  name: string;
  namespace: string;
  display_name: string;
  description: string;
  kind: string | null;
  hosting: 'internal' | 'external';
  backing_name: string | null;
  phase: string | null;
  ready: boolean;
  endpoint: string | null;
  subscriptions: MaasModelSubscriptionRef[];
  // null means "couldn't tell" (RBAC/read failure) — never collapse into false.
  has_auth_policy: boolean | null;
  gateway_access_label: boolean | null;
  external_providers: MaasExternalProviderRef[];
  serving: MaasServingInfo | null;
  raw: unknown;
  raw_yaml: string;
}

export interface MaasAuthPolicy {
  name: string;
  namespace: string;
  display_name: string;
  owner: { groups: string[]; users: string[] };
  models: { name: string; namespace: string }[];
  ready: boolean;
  raw_yaml: string;
}

export interface MaasAccessSubscriptionRef {
  name: string;
  display_name: string;
  priority: number | null;
  raw_yaml: string;
}

export interface MaasAccessPolicyRef {
  name: string;
  display_name: string;
  ready: boolean;
  raw_yaml: string;
}

export interface MaasAccessRow {
  name: string;
  users: string[] | null;
  raw_yaml: string | null;
  subscriptions: MaasAccessSubscriptionRef[];
  auth_policies: MaasAccessPolicyRef[];
  quota_without_access: string[];
  access_without_quota: string[];
}

export interface MaasTokenRateLimitPolicy {
  name: string;
  namespace: string;
  target_kind: string | null;
  target_name: string | null;
  limit_names: string[];
  accepted: boolean;
  enforced: boolean;
  raw_yaml: string;
}

export interface MaasLimitador {
  name: string;
  namespace: string;
  limit_count: number;
  ready: boolean;
  service_host: string | null;
  raw_yaml: string;
}

export interface MaasGateway {
  name: string;
  namespace: string;
  gateway_class: string | null;
  address: string | null;
  programmed: boolean;
  raw_yaml: string;
}

export interface MaasHttpRoute {
  name: string;
  namespace: string;
  parent_gateway: string | null;
  parent_gateway_namespace: string | null;
  owning_model: string | null;
  raw_yaml: string;
}

export interface MaasTenant {
  name: string;
  namespace: string;
  gateway_ref: { name: string; namespace: string } | null;
  max_api_key_expiration_days: number | null;
  telemetry_enabled: boolean | null;
  phase: string | null;
  raw_yaml: string;
}

export interface MaasDataScienceCluster {
  name: string;
  maas_management_state: string | null;
  maas_field_path: string | null;
  raw_yaml: string;
}

export interface MaasOdhDashboardConfig {
  name: string;
  model_as_service: boolean | null;
  external_models: boolean | null;
  gen_ai_studio: boolean | null;
  observability_dashboard: boolean | null;
  raw_yaml: string;
}

export interface MaasPlatformSection<T> {
  available: boolean;
  reason: string | null;
  item: T | null;
}

export interface MaasPlatform {
  tenants: MaasSectionResult<MaasTenant>;
  data_science_cluster: MaasPlatformSection<MaasDataScienceCluster>;
  odh_dashboard_config: MaasPlatformSection<MaasOdhDashboardConfig>;
}

export interface MaasSectionResult<T> {
  available: boolean;
  reason: string | null;
  items: T[];
}

async function fetchMaasSection<T>(path: string): Promise<MaasSectionResult<T>> {
  try {
    const r = await fetch(path);
    if (!r.ok) return { available: false, reason: `http_${r.status}`, items: [] };
    return (await r.json()) as MaasSectionResult<T>;
  } catch {
    return { available: false, reason: 'network_error', items: [] };
  }
}

export function getMaasSubscriptions(): Promise<MaasSectionResult<MaasSubscription>> {
  return fetchMaasSection('/api/maas/subscriptions');
}

export function getMaasModels(): Promise<MaasSectionResult<MaasModel>> {
  return fetchMaasSection('/api/maas/models');
}

export function getMaasAccess(): Promise<MaasSectionResult<MaasAccessRow>> {
  return fetchMaasSection('/api/maas/access');
}

export function getMaasAuthPolicies(): Promise<MaasSectionResult<MaasAuthPolicy>> {
  return fetchMaasSection('/api/maas/auth-policies');
}

export function getMaasRateLimitPolicies(): Promise<MaasSectionResult<MaasTokenRateLimitPolicy>> {
  return fetchMaasSection('/api/maas/rate-limit-policies');
}

export function getMaasLimitador(): Promise<MaasSectionResult<MaasLimitador>> {
  return fetchMaasSection('/api/maas/limitador');
}

export function getMaasGateways(): Promise<MaasSectionResult<MaasGateway>> {
  return fetchMaasSection('/api/maas/gateways');
}

export function getMaasHttpRoutes(): Promise<MaasSectionResult<MaasHttpRoute>> {
  return fetchMaasSection('/api/maas/http-routes');
}

const UNAVAILABLE_PLATFORM: MaasPlatform = {
  tenants: { available: false, reason: 'network_error', items: [] },
  data_science_cluster: { available: false, reason: 'network_error', item: null },
  odh_dashboard_config: { available: false, reason: 'network_error', item: null },
};

export async function getMaasPlatform(): Promise<MaasPlatform> {
  try {
    const r = await fetch('/api/maas/platform');
    if (!r.ok) return UNAVAILABLE_PLATFORM;
    return (await r.json()) as MaasPlatform;
  } catch {
    return UNAVAILABLE_PLATFORM;
  }
}

