import { apiClient } from '@core/lib/api-client'

export interface InsightSettings {
  github_token_set: boolean
  lang: string
  has_access: boolean
  has_tldr_access: boolean
  tldr_model: string | null
  tldr_allowed_models: string[]
  granted_at?: string | null
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

export const insightApi = {
  getSettings: () =>
    apiClient.get<InsightSettings>('/insight/settings/me'),

  patchSettings: (body: { lang?: string; tldr_model?: string | null; github_token?: string | null }) =>
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
}
