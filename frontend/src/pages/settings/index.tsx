import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { apiClient } from '@core/lib/api-client'
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

interface InsightSettings {
  lang: string
  has_access: boolean
}

const LANG_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Русский' },
] as const

export default function InsightSettingsPage() {
  const { t } = useTranslation()
  const [data, setData] = useState<InsightSettings | null>(null)
  const [lang, setLang] = useState('en')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiClient
      .get<InsightSettings>('/insight/settings/me')
      .then((res) => {
        setData(res.data)
        setLang(res.data.lang)
      })
      .catch(() => {}) // silently handle - page renders locked state for no-access
      .finally(() => setLoading(false))
  }, [t])

  const save = async () => {
    setSaving(true)
    try {
      const res = await apiClient.patch<InsightSettings>('/insight/settings/me', { lang })
      setData(res.data)
      setLang(res.data.lang)
      toast.success(t('common.save'))
    } catch {
      toast.error(t('common.load_error'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-24 text-muted-foreground">{t('common.loading')}</div>
  }

  const dirty = data !== null && lang !== data.lang

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('insight.settings_lang_title')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {data?.has_access ? (
            <>
              <p className="text-sm text-muted-foreground">{t('insight.settings_lang_hint')}</p>
              <div className="space-y-1.5 max-w-xs">
                <Label>{t('insight.settings_lang_label')}</Label>
                <Select value={lang} onValueChange={setLang}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {LANG_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex justify-end pt-2">
                <Button onClick={save} disabled={saving || !dirty} className="w-full sm:w-auto">
                  {saving ? t('common.saving') : t('common.save')}
                </Button>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t('insight.settings_no_access_body')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
