export type CredentialEdit =
  | { kind: 'unchanged' }
  | { kind: 'replace'; value: string }
  | { kind: 'clear' }

export const KEEP_CREDENTIAL: CredentialEdit = { kind: 'unchanged' }

// Empty input cancels a replacement; only the clear action deletes a stored key.
export function editCredential(value: string): CredentialEdit {
  return value ? { kind: 'replace', value } : KEEP_CREDENTIAL
}

export function credentialValue(edit: CredentialEdit): string | undefined {
  if (edit.kind === 'unchanged') return undefined
  return edit.kind === 'clear' ? '' : edit.value
}

export function credentialField<K extends string>(name: K, edit: CredentialEdit): Partial<Record<K, string>> {
  const value = credentialValue(edit)
  return value === undefined ? {} : { [name]: value } as Record<K, string>
}

export function credentialQuery(url?: string, apiKey?: string): string {
  const params = new URLSearchParams()
  if (url) params.set('url', url)
  if (apiKey !== undefined) params.set('api_key', apiKey)
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}
