import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrainCircuit, LockKeyhole } from 'lucide-react'

import { apiClient } from '@core/lib/api-client'
import { formatDate } from '@core/lib/utils'
import { Button } from '@core/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@core/components/ui/card'
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
  granted_at?: string | null
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
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [t])

  const save = async () => {
    setSaving(true)
    try {
      const res = await apiClient.patch<InsightSettings>('/insight/settings/me', { lang })
      setData(res.data)
      setLang(res.data.lang)
      toast.success(t('common.saved'))
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
      {/* Access status */}
      <Card>
        <CardContent className="pt-5">
          {data?.has_access ? (
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10">
                <BrainCircuit className="h-4 w-4 text-primary" />
              </div>
              <div>
                <p className="text-sm font-medium">{t('insight.settings_access_active', { defaultValue: 'Access active' })}</p>
                {data.granted_at && (
                  <p className="text-xs text-muted-foreground">
                    {t('insight.settings_access_granted', { date: formatDate(data.granted_at) })}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted">
                <LockKeyhole className="h-4 w-4 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-medium">{t('insight.settings_no_access_title')}</p>
                <p className="text-xs text-muted-foreground">{t('insight.settings_no_access_body')}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Language */}
      <Card>
        <CardHeader>
          <CardTitle>{t('insight.settings_lang_title')}</CardTitle>
          <CardDescription>{t('insight.settings_lang_hint')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {data?.has_access ? (
            <>
              <div className="space-y-1.5">
                <Label>{t('insight.settings_lang_label')}</Label>
                <Select value={lang} onValueChange={setLang}>
                  <SelectTrigger className="w-full max-w-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LANG_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={save}
                disabled={saving || !dirty}
                size="sm"
                className="w-full sm:w-auto"
              >
                {saving ? t('common.saving') : t('common.save')}
              </Button>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{t('insight.settings_no_access_body')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
