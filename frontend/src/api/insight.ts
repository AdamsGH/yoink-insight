import { apiClient } from '@core/lib/api-client'

export interface InsightSettings {
  lang: string
  has_access: boolean
  granted_at?: string | null
  [key: string]: unknown
}

export const insightApi = {
  getSettings: () =>
    apiClient.get<InsightSettings>('/insight/settings/me'),

  patchSettings: (body: Partial<InsightSettings>) =>
    apiClient.patch<InsightSettings>('/insight/settings/me', body),
}
