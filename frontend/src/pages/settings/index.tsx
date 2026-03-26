import { useEffect, useState } from 'react'

import { apiClient } from '@core/lib/api-client'
import { formatDate } from '@core/lib/utils'
import type { InsightAccess } from '@insight/types'
import { Button } from '@core/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@core/components/ui/card'
import { Label } from '@core/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@core/components/ui/select'
import { toast } from '@core/components/ui/toast'

const LANG_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Русский' },
  { value: 'uk', label: 'Українська' },
  { value: 'de', label: 'Deutsch' },
  { value: 'fr', label: 'Français' },
  { value: 'es', label: 'Español' },
  { value: 'zh', label: '中文' },
  { value: 'ja', label: '日本語' },
]

export default function InsightSettingsPage() {
  const [data, setData] = useState<InsightAccess | null>(null)
  const [lang, setLang] = useState('en')
  const [loading, setLoading] = useState(true)
  const [noAccess, setNoAccess] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiClient
      .get<InsightAccess>('/insight/settings/me')
      .then((res) => {
        setData(res.data)
        setLang(res.data.lang)
      })
      .catch((err) => {
        if (err?.response?.status === 404 || err?.response?.status === 403) {
          setNoAccess(true)
        } else {
          toast.error('Failed to load Insight settings')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      const res = await apiClient.patch<InsightAccess>('/insight/settings/me', { lang })
      setData(res.data)
      setLang(res.data.lang)
      toast.success('Language updated')
    } catch {
      toast.error('Failed to update language')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-24 text-muted-foreground">Loading...</div>
    )
  }

  if (noAccess) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">AI Insight Settings</h1>
        <Card>
          <CardContent className="pt-6">
            <p className="text-muted-foreground">
              You don't have Insight access. Ask an admin to grant it.
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const dirty = data !== null && lang !== data.lang

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">AI Insight Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Response Language</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Gemini will reply in the selected language for /about and /summary.
          </p>
          <div className="space-y-1.5 max-w-xs">
            <Label>Language</Label>
            <Select value={lang} onValueChange={setLang}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANG_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {data && (
            <p className="text-xs text-muted-foreground">
              Access granted on {formatDate(data.granted_at)}
            </p>
          )}
          <div className="flex justify-end pt-2">
            <Button onClick={save} disabled={saving || !dirty} className="w-full sm:w-auto">
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
