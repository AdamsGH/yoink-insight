import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

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
  { value: 'en', key: 'lang_en' },
  { value: 'ru', key: 'lang_ru' },
] as const

export default function InsightSettingsPage() {
  const { t } = useTranslation()
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
          toast.error(t('common.load_error'))
        }
      })
      .finally(() => setLoading(false))
  }, [t])

  const save = async () => {
    setSaving(true)
    try {
      const res = await apiClient.patch<InsightAccess>('/insight/settings/me', { lang })
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
    return (
      <div className="flex justify-center py-24 text-muted-foreground">{t('common.loading')}</div>
    )
  }

  if (noAccess) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">{t('insight.settings_title')}</h1>
        <Card>
          <CardContent className="pt-6">
            <p className="text-muted-foreground">{t('insight.settings_no_access_body')}</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const dirty = data !== null && lang !== data.lang

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{t('insight.settings_title')}</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('insight.settings_lang_title')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{t('insight.settings_lang_hint')}</p>
          <div className="space-y-1.5 max-w-xs">
            <Label>{t('insight.settings_lang_label')}</Label>
            <Select value={lang} onValueChange={setLang}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LANG_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {t(`insight.${o.key}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {data && (
            <p className="text-xs text-muted-foreground">
              {t('insight.settings_access_granted', { date: formatDate(data.granted_at) })}
            </p>
          )}
          <div className="flex justify-end pt-2">
            <Button onClick={save} disabled={saving || !dirty} className="w-full sm:w-auto">
              {saving ? t('common.loading') : t('common.save')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
