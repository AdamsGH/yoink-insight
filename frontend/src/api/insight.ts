import { apiClient } from '@core/lib/api-client'

export interface InsightSettings {
  github_token_set: boolean
  lang: string
  has_gemini_access: boolean
  has_tldr_access: boolean
  has_tldr_gateway_access: boolean
  has_search_access: boolean
  has_search_gateway_access: boolean
  tldr_model: string | null
  tldr_allowed_models: string[]
  use_search: boolean
  prompts: Record<string, string>
  prompt_defaults: Record<string, string>
  alias_defaults: Record<string, string>
  granted_at?: string | null
}

export interface InsightSettingsPatch {
  lang?: string
  tldr_model?: string | null
  github_token?: string | null
  use_search?: boolean
  prompts?: Record<string, string | null>
}

export interface TldrConfig {
  allowed_models: string[]
  default_model: string
  gateway_base_url: string
  gateway_api_key: string
}

export interface GatewayModel {
  id: string
  [key: string]: unknown
}

export interface TldrAlias {
  id: number
  aliases: string | null
  prompt: string | null
  domains: string | null
  target_alias: string | null
  created_at: string
}

export interface TldrAliasInput {
  aliases?: string | null
  prompt?: string | null
  domains?: string | null
  target_alias?: string | null
}

// ---------------------------------------------------------------------------
// BYOK (Bring Your Own Key)
// ---------------------------------------------------------------------------

export interface ByokModelInfo {
  id: string
  supports_websearch: boolean
}

export interface ByokProviderInfo {
  id: string
  label: string
  default_base_url: string | null
  requires_base_url: boolean
  api_shape: 'openai' | 'anthropic'
  all_websearch: boolean
}

export interface ByokConfig {
  enabled: boolean
  has_config: boolean
  api_key_set: boolean
  api_key_masked: string | null
  provider: string | null
  base_url: string | null
  model: string | null
  models: ByokModelInfo[]
  models_fetched_at: string | null
  tested_at: string | null
  test_error: string | null
  providers: ByokProviderInfo[]
}

export interface ByokConfigUpdate {
  provider: string
  base_url?: string | null
  api_key?: string | null
  model: string
}

export interface ByokTestRequest {
  provider: string
  base_url?: string | null
  api_key?: string | null
}

export interface ByokTestResponse {
  ok: boolean
  error: string | null
  models: ByokModelInfo[]
}

export interface ByokAdminConfig {
  enabled: boolean
}

export interface GithubDeviceFlowStart {
  user_code: string
  verification_uri: string
  expires_at: number
  interval: number
  status: string
}

export interface GithubDeviceFlowStatus {
  status: 'none' | 'pending' | 'success' | 'expired' | 'error'
  user_code?: string
  verification_uri?: string
  expires_at?: number
  interval?: number
  error?: string | null
  username?: string | null
}

export const insightApi = {
  getSettings: () =>
    apiClient.get<InsightSettings>('/insight/settings/me'),

  patchSettings: (body: InsightSettingsPatch) =>
    apiClient.patch<InsightSettings>('/insight/settings/me', body),

  getTldrConfig: () =>
    apiClient.get<TldrConfig>('/insight/config/tldr'),

  patchTldrConfig: (body: TldrConfig) =>
    apiClient.patch<TldrConfig>('/insight/config/tldr', body),

  listModels: () =>
    apiClient.get<GatewayModel[]>('/insight/models'),

  testGateway: (url?: string, apiKey?: string) => {
    const params = new URLSearchParams()
    if (url) params.set('url', url)
    if (apiKey) params.set('api_key', apiKey)
    const qs = params.toString()
    return apiClient.get<{ ok: boolean; error?: string; model_count?: number; url: string }>(
      `/insight/config/test${qs ? `?${qs}` : ''}`
    )
  },

  listAliases: () =>
    apiClient.get<TldrAlias[]>('/insight/aliases'),

  createAlias: (body: TldrAliasInput) =>
    apiClient.post<TldrAlias>('/insight/aliases', body),

  updateAlias: (id: number, body: TldrAliasInput) =>
    apiClient.patch<TldrAlias>(`/insight/aliases/${id}`, body),

  deleteAlias: (id: number) =>
    apiClient.delete(`/insight/aliases/${id}`),

  // BYOK
  getByok: () =>
    apiClient.get<ByokConfig>('/insight/byok/me'),

  saveByok: (body: ByokConfigUpdate) =>
    apiClient.put<ByokConfig>('/insight/byok/me', body),

  deleteByok: () =>
    apiClient.delete('/insight/byok/me'),

  testByok: (body: ByokTestRequest) =>
    apiClient.post<ByokTestResponse>('/insight/byok/me/test', body),

  refreshByokModels: () =>
    apiClient.post<ByokConfig>('/insight/byok/me/refresh-models'),

  getByokAdmin: () =>
    apiClient.get<ByokAdminConfig>('/insight/config/byok'),

  setByokAdmin: (body: ByokAdminConfig) =>
    apiClient.patch<ByokAdminConfig>('/insight/config/byok', body),

  // GitHub OAuth device-flow login
  startGithubLogin: () =>
    apiClient.post<GithubDeviceFlowStart>('/insight/github/login'),

  getGithubLoginStatus: () =>
    apiClient.get<GithubDeviceFlowStatus>('/insight/github/login/status'),

  deleteGithubToken: () =>
    apiClient.delete('/insight/github/token'),

  // GitHub write access (public_repo scope)
  startPublicRepoLogin: () =>
    apiClient.post<GithubDeviceFlowStart>('/insight/github/upgrade-scope'),

  getPublicRepoLoginStatus: () =>
    apiClient.get<GithubDeviceFlowStatus>('/insight/github/upgrade-scope/status'),

  getWriteTokenStatus: () =>
    apiClient.get<{ enabled: boolean; configured: boolean }>('/insight/github/write-token/status'),

  deleteWriteToken: () =>
    apiClient.delete('/insight/github/write-token'),
}
