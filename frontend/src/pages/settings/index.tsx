import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrainCircuit, LockKeyhole } from 'lucide-react'

import { apiClient } from '@core/lib/api-client'
import { formatDate } from '@core/lib/utils'
import { Button } from '@core/components/ui/button'
import { Card, CardContent } from '@core/components/ui/card'
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
    <div className="space-y-3">
      <Card>
        <CardContent className="pt-4 pb-4">
          {data?.has_access ? (
            <div className="flex items-center gap-3">
              <BrainCircuit className="h-5 w-5 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="text-sm font-medium leading-none">
                  {t('insight.settings_access_active', { defaultValue: 'Access active' })}
                </p>
                {data.granted_at && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t('insight.settings_access_granted', { date: formatDate(data.granted_at) })}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <LockKeyhole className="h-5 w-5 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <p className="text-sm font-medium leading-none">{t('insight.settings_no_access_title')}</p>
                <p className="mt-1 text-xs text-muted-foreground">{t('insight.settings_no_access_body')}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-4 space-y-4">
          <div>
            <p className="text-sm font-medium">{t('insight.settings_lang_title')}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t('insight.settings_lang_hint')}</p>
          </div>
          {data?.has_access ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="space-y-1.5 flex-1 max-w-xs">
                <Label className="text-xs text-muted-foreground">{t('insight.settings_lang_label')}</Label>
                <Select value={lang} onValueChange={setLang}>
                  <SelectTrigger>
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
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('insight.settings_no_access_body')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
