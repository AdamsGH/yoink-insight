import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrainCircuit, Link, LockKeyhole } from 'lucide-react'

import { insightApi, type InsightSettings } from '@insight/api/insight'
import { formatDate } from '@core/lib/utils'
import { Button, Card, CardContent, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@ui'
import { toast } from '@core/components/ui/toast'

const LANG_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Русский' },
] as const

export default function InsightSettingsPage() {
  const { t } = useTranslation()
  const [data, setData] = useState<InsightSettings | null>(null)
  const [lang, setLang] = useState('en')
  const [tldrModel, setTldrModel] = useState<string>('')
  const [githubToken, setGithubToken] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    insightApi
      .getSettings()
      .then((res) => {
        setData(res.data)
        setLang(res.data.lang)
        setTldrModel(res.data.tldr_model ?? res.data.tldr_allowed_models[0] ?? '')
        setGithubToken('')
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      const body: { lang?: string; tldr_model?: string | null; github_token?: string | null } = { lang }
      if (data?.has_tldr_access) {
        body.tldr_model = tldrModel || null
        if (githubToken !== '') body.github_token = githubToken || null
      }
      const res = await insightApi.patchSettings(body)
      setData(res.data)
      setLang(res.data.lang)
      setTldrModel(res.data.tldr_model ?? res.data.tldr_allowed_models[0] ?? '')
      setGithubToken('')
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

  const langDirty = data !== null && lang !== data.lang
  const tldrDirty = data !== null && data.has_tldr_access && tldrModel !== (data.tldr_model ?? data.tldr_allowed_models[0] ?? '')
  const githubDirty = data !== null && data.has_tldr_access && githubToken !== ''
  const dirty = langDirty || tldrDirty || githubDirty

  return (
    <div className="space-y-3">
      {/* AI Summary access */}
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

      {/* Language */}
      <Card>
        <CardContent className="pt-4 space-y-4">
          <div>
            <p className="text-sm font-medium">{t('insight.settings_lang_title')}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t('insight.settings_lang_hint')}</p>
          </div>
          {data?.has_access ? (
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">{t('insight.settings_lang_label')}</Label>
              <Select value={lang} onValueChange={setLang}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANG_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t('insight.settings_no_access_body')}</p>
          )}
        </CardContent>
      </Card>

      {/* TL;DR */}
      <Card>
        <CardContent className="pt-4 pb-4 space-y-4">
          <div className="flex items-center gap-3">
            {data?.has_tldr_access ? (
              <Link className="h-5 w-5 shrink-0 text-primary" />
            ) : (
              <LockKeyhole className="h-5 w-5 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0">
              <p className="text-sm font-medium leading-none">
                {t('insight.tldr_title', { defaultValue: 'TL;DR' })}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {data?.has_tldr_access
                  ? t('insight.tldr_access_active', { defaultValue: 'Access active - summarise any URL with /tldr' })
                  : t('insight.tldr_no_access', { defaultValue: 'No TL;DR access. Ask an admin.' })}
              </p>
            </div>
          </div>

          {data?.has_tldr_access && data.tldr_allowed_models.length > 0 && (
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">
                {t('insight.tldr_model_label', { defaultValue: 'LLM model' })}
              </Label>
              <Select value={tldrModel} onValueChange={setTldrModel}>
                <SelectTrigger className="w-full font-mono text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {data.tldr_allowed_models.map((m) => (
                    <SelectItem key={m} value={m} className="font-mono text-xs">{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {data?.has_tldr_access && (
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">
                {t('insight.github_token_label', { defaultValue: 'GitHub token (optional)' })}
              </Label>
              <Input
                type="password"
                placeholder={data.github_token_set
                  ? t('insight.github_token_placeholder_set', { defaultValue: 'Enter new token to replace saved one' })
                  : t('insight.github_token_placeholder_empty', { defaultValue: 'ghp_...' })
                }
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                {t('insight.github_token_hint', { defaultValue: 'For private repos and to avoid GitHub rate limits.' })}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Save */}
      {(data?.has_access || data?.has_tldr_access) && (
        <Button
          onClick={save}
          disabled={saving || !dirty}
          size="sm"
          className="w-full"
        >
          {saving ? t('common.saving') : t('common.save')}
        </Button>
      )}
    </div>
  )
}
