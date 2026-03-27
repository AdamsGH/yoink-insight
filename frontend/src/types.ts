export interface InsightAccess {
  user_id: number
  lang: string
  granted_by: number
  granted_at: string
  username: string | null
  first_name: string | null
  granted_by_username: string | null
}

export interface InsightSettings {
  lang: string
}

export interface UserLookupResult {
  id: number
  username: string | null
  first_name: string | null
}
