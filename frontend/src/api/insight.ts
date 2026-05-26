import { apiClient } from '@core/lib/api-client'

export interface InsightSettings {
  github_token_set: boolean
  lang: string
  has_gemini_access: boolean
  has_tldr_access: boolean
  has_search_access: boolean
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
}
