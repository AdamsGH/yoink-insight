import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Globe, KeyRound, RefreshCw, Trash2 } from 'lucide-react'

import CredentialInput from '@insight/components/CredentialInput'
import { credentialField, KEEP_CREDENTIAL, type CredentialEdit } from '@insight/api/credentials'
import {
  insightApi,
  type ByokConfig,
  type ByokModelInfo,
  type ByokProviderInfo,
  type InsightSettings,
} from '@insight/api/insight'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  Button, Card, CardContent, CardHeader, CardTitle,
  Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList,
  Input, Label,
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@ui'
import { toast } from '@core/components/ui/toast'

interface Props {
  data: ByokConfig
  onChange: (next: ByokConfig) => void
  onAccessChange: (next: InsightSettings) => void
}

export default function ByokCard({ data, onChange, onAccessChange }: Props) {
  const { t } = useTranslation()

  const [provider, setProvider] = useState<string>(data.provider ?? '')
  const [baseUrl, setBaseUrl] = useState<string>(data.base_url ?? '')
  const [apiKey, setApiKey] = useState<CredentialEdit>(KEEP_CREDENTIAL)
  const [model, setModel] = useState<string>(data.model ?? '')

  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [models, setModels] = useState<ByokModelInfo[]>(data.models)
  const [probeError, setProbeError] = useState<string | null>(data.test_error)
  const [probeOk, setProbeOk] = useState(!!data.tested_at && !data.test_error)
  const [probeInputs, setProbeInputs] = useState({ provider: data.provider ?? '', baseUrl: data.base_url ?? '', apiKey: KEEP_CREDENTIAL })
  const probeMatchesDraft = probeInputs.provider === provider && probeInputs.baseUrl === baseUrl && probeInputs.apiKey === apiKey
  const [warnModelId, setWarnModelId] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Sync local state when the parent reloads the config (after save/refresh).
  useEffect(() => {
    setProvider(data.provider ?? '')
    setBaseUrl(data.base_url ?? '')
    setApiKey(KEEP_CREDENTIAL)
    setModel(data.model ?? '')
    setModels(data.models)
    setProbeError(data.test_error)
    setProbeOk(!!data.tested_at && !data.test_error)
    setProbeInputs({ provider: data.provider ?? '', baseUrl: data.base_url ?? '', apiKey: KEEP_CREDENTIAL })
  }, [data])

  const providers = data.providers
  const providerSpec: ByokProviderInfo | null = useMemo(
    () => providers.find((p) => p.id === provider) ?? null,
    [providers, provider],
  )

  const requiresBaseUrl = providerSpec?.requires_base_url ?? false
  const canSubmitProbe = !!provider && (!requiresBaseUrl || !!baseUrl.trim()) && (
    apiKey.kind === 'unchanged' ? data.api_key_set : apiKey.kind === 'replace'
  )

  const onProviderChange = (next: string) => {
    setProvider(next)
    const spec = providers.find((p) => p.id === next)
    // Reset base_url to the new provider's default when switching unless the
    // new provider requires custom URL.
    if (spec) {
      setBaseUrl(spec.requires_base_url ? '' : (spec.default_base_url ?? ''))
    }
    setModels([])
    setModel('')
    setApiKey(KEEP_CREDENTIAL)
  }

  const runTest = async () => {
    setTesting(true)
    try {
      const res = await insightApi.testByok({
        provider,
        base_url: baseUrl.trim() || null,
        ...credentialField('api_key', apiKey),
      })
      setProbeInputs({ provider, baseUrl, apiKey })
      if (res.data.ok) {
        setProbeError(null)
        setProbeOk(true)
        setModels(res.data.models)
        toast.success(t('insight.byok.test_ok', {
          defaultValue: '{{count}} models available',
          count: res.data.models.length,
        }))
        if (!model && res.data.models.length > 0) {
          // Prefer a websearch-capable model by default.
          const ws = res.data.models.find((m) => m.supports_websearch)
          setModel((ws ?? res.data.models[0]).id)
        }
      } else {
        setProbeOk(false)
        setProbeError(res.data.error)
        toast.error(t(`insight.byok.test_err.${res.data.error}`, {
          defaultValue: res.data.error ?? 'Probe failed',
        }))
      }
    } catch {
      setProbeOk(false)
      setProbeError('network_error')
      toast.error(t('common.load_error'))
    } finally {
      setTesting(false)
    }
  }

  const commitSave = async (chosenModel: string) => {
    setSaving(true)
    try {
      const res = await insightApi.saveByok({
        provider,
        base_url: baseUrl.trim() || null,
        ...credentialField('api_key', apiKey),
        model: chosenModel,
      })
      setApiKey(KEEP_CREDENTIAL)
      onChange(res.data)
      setProbeError(res.data.test_error)
      setProbeOk(!res.data.test_error && !!res.data.tested_at)
      void insightApi.getSettings().then((settings) => onAccessChange(settings.data)).catch(() => toast.error(t('common.load_error')))
      if (res.data.test_error) {
        toast.error(t(`insight.byok.test_err.${res.data.test_error}`, {
          defaultValue: res.data.test_error,
        }))
      } else {
        toast.success(t('common.saved'))
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? t('common.load_error'))
    } finally {
      setSaving(false)
    }
  }

  const onSaveClick = () => {
    if (!provider || !model) return
    const chosen = models.find((m) => m.id === model)
    if (apiKey.kind !== 'clear' && chosen && !chosen.supports_websearch) {
      setWarnModelId(model)
      return
    }
    void commitSave(model)
  }

  const onConfirmWarn = () => {
    const m = warnModelId
    setWarnModelId(null)
    if (m) void commitSave(m)
  }

  const refreshModels = async () => {
    if (!data.has_config) return
    setRefreshing(true)
    try {
      const res = await insightApi.testByok({
        provider,
        base_url: baseUrl.trim() || null,
        ...credentialField('api_key', apiKey),
      })
      setProbeInputs({ provider, baseUrl, apiKey })
      if (!res.data.ok) {
        setProbeOk(false)
        setProbeError(res.data.error)
        toast.error(t(`insight.byok.test_err.${res.data.error}`, {
          defaultValue: res.data.error ?? 'Probe failed',
        }))
        return
      }
      setProbeError(null)
      setProbeOk(true)
      setModels(res.data.models)
      toast.success(t('insight.byok.test_ok', {
        defaultValue: '{{count}} models available',
        count: res.data.models.length,
      }))
    } catch {
      setProbeOk(false)
      setProbeError('network_error')
      toast.error(t('common.load_error'))
    } finally {
      setRefreshing(false)
    }
  }

  const removeConfig = async () => {
    setConfirmDelete(false)
    try {
      await insightApi.deleteByok()
      const res = await insightApi.getByok()
      onChange(res.data)
      void insightApi.getSettings().then((settings) => onAccessChange(settings.data)).catch(() => toast.error(t('common.load_error')))
      setProbeError(null)
      setProbeOk(false)
      setProvider('')
      setBaseUrl('')
      setApiKey(KEEP_CREDENTIAL)
      setModel('')
      setModels([])
      toast.success(t('common.deleted', { defaultValue: 'Deleted' }))
    } catch {
      toast.error(t('common.load_error'))
    }
  }

  const selectedModelInfo = models.find((m) => m.id === model) ?? null

  return (
    <Card>
      <CardHeader className="px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="h-4 w-4 shrink-0 text-primary" />
            {t('insight.byok.title', { defaultValue: 'Bring Your Own Key' })}
          </CardTitle>
          <span className="text-xs font-medium text-muted-foreground">
            {data.has_config
              ? t('insight.byok.status_set', { defaultValue: 'configured' })
              : t('insight.byok.status_empty', { defaultValue: 'not set' })}
          </span>
        </div>
        <p className="text-xs text-muted-foreground leading-snug">
          {t('insight.byok.hint', {
            defaultValue: 'Route /tldr through your own LLM provider. Models with a green tint support web search; pick those for best results on news / web pages.',
          })}
        </p>
      </CardHeader>
      <CardContent className="px-4 pb-3 space-y-3">
        {/* Provider */}
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">
            {t('insight.byok.provider_label', { defaultValue: 'Provider' })}
          </Label>
          <Select value={provider} onValueChange={onProviderChange}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder={t('insight.byok.provider_placeholder', { defaultValue: 'Pick a provider...' })} />
            </SelectTrigger>
            <SelectContent>
              {providers.map((p) => (
                <SelectItem key={p.id} value={p.id} className="text-xs">
                  {p.label}
                  {p.all_websearch && (
                    <Globe className="ml-1.5 inline h-3 w-3 text-emerald-500" />
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Base URL */}
        {provider && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              {t('insight.byok.base_url_label', { defaultValue: 'Base URL' })}
              {requiresBaseUrl && <span className="ml-1 text-destructive">*</span>}
            </Label>
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={providerSpec?.default_base_url ?? 'https://...'}
              className="h-8 font-mono text-xs"
            />
            {!requiresBaseUrl && (
              <p className="text-xs text-muted-foreground">
                {t('insight.byok.base_url_hint', {
                  defaultValue: 'Leave empty to use the provider default ({{url}}).',
                  url: providerSpec?.default_base_url ?? '',
                })}
              </p>
            )}
          </div>
        )}

        {/* API key */}
        {provider && (
          <div className="space-y-1.5">
            <Label htmlFor="byok-api-key" className="text-xs text-muted-foreground">
              {t('insight.byok.api_key_label', { defaultValue: 'API key' })}
            </Label>
            <CredentialInput id="byok-api-key" value={apiKey} stored={data.api_key_set} disabled={saving} onChange={setApiKey} />
          </div>
        )}

        {/* Test connection + load models */}
        {provider && (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs"
              disabled={!canSubmitProbe || testing}
              onClick={runTest}
            >
              {testing
                ? t('common.loading')
                : t('insight.byok.test_btn', { defaultValue: 'Test connection' })}
            </Button>
            {data.has_config && (
              <Button
                size="sm"
                variant="ghost"
                className="h-8 w-8 p-0"
                disabled={refreshing || !canSubmitProbe}
                onClick={refreshModels}
                title={t('insight.byok.refresh_btn', { defaultValue: 'Refresh model list' })}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
              </Button>
            )}
            {probeMatchesDraft && probeOk && (
              <span className="text-xs text-green-600 dark:text-green-400 inline-flex items-center gap-1">
                <Check className="h-3 w-3" />
                {t('insight.byok.tested_ok', { defaultValue: 'verified' })}
              </span>
            )}
            {probeMatchesDraft && probeError && (
              <span className="text-xs text-destructive inline-flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                {t(`insight.byok.test_err.${probeError}`, {
                  defaultValue: probeError === 'http_403'
                    ? t('insight.byok.test_err.provider_forbidden', { defaultValue: 'Provider denied the request. Check key permissions or account restrictions.' })
                    : probeError,
                })}
              </span>
            )}
          </div>
        )}

        {/* Model picker - same Combobox shape as InsightSettingsPage tldr_model */}
        {provider && models.length > 0 && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                {t('insight.byok.model_label', { defaultValue: 'Model' })}
              </Label>
              <span className="text-[10px] text-muted-foreground inline-flex items-center gap-1">
                <Globe className="h-3 w-3 text-emerald-500" />
                {t('insight.byok.websearch_legend', { defaultValue: 'supports web search' })}
              </span>
            </div>
            <Combobox<ByokModelInfo>
              value={selectedModelInfo}
              onValueChange={(m: ByokModelInfo | null) => setModel(m?.id ?? '')}
              items={models}
              itemToStringLabel={(m: ByokModelInfo) => m.id}
              itemToStringValue={(m: ByokModelInfo) => m.id}
            >
              <ComboboxInput
                placeholder={t('insight.byok.model_placeholder', { defaultValue: 'Select model...' })}
                className="h-8 text-xs font-mono w-full"
                showClear
              />
              <ComboboxContent>
                <ComboboxEmpty>{t('common.no_results', { defaultValue: 'No models found' })}</ComboboxEmpty>
                <ComboboxList>
                  {(m: ByokModelInfo) => (
                    <ComboboxItem
                      key={m.id}
                      value={m}
                      className={`font-mono text-xs ${m.supports_websearch ? 'bg-emerald-500/10 data-highlighted:bg-emerald-500/20 data-selected:bg-emerald-500/25' : ''}`}
                    >
                      <span className="flex-1 truncate">{m.id}</span>
                      {m.supports_websearch && (
                        <Globe className="ml-2 h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                      )}
                    </ComboboxItem>
                  )}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
            {selectedModelInfo && !selectedModelInfo.supports_websearch && (
              <div className="flex items-start gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/5 px-2 py-1.5">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                <p className="text-[11px] leading-snug text-muted-foreground">
                  {t('insight.byok.no_websearch_warn', {
                    defaultValue: 'This model is not known to support web search. /tldr will only see the page content we fetch.',
                  })}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Save row */}
        {provider && (
          <div className="flex items-center gap-2 pt-1">
            <Button
              size="sm"
              className="h-8"
              disabled={saving || !provider || !model || (!canSubmitProbe && apiKey.kind !== 'clear')}
              onClick={onSaveClick}
            >
              {saving ? t('common.saving') : t('common.save')}
            </Button>
            {data.has_config && (
              <Button
                size="sm"
                variant="ghost"
                className="h-8 text-muted-foreground hover:text-destructive"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                {t('insight.byok.delete_btn', { defaultValue: 'Remove' })}
              </Button>
            )}
          </div>
        )}
      </CardContent>

      {/* Warn about non-websearch model */}
      <AlertDialog open={warnModelId !== null} onOpenChange={(o) => { if (!o) setWarnModelId(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('insight.byok.no_websearch_title', { defaultValue: 'Model without web search' })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('insight.byok.no_websearch_body', {
                defaultValue: '"{{model}}" is not known to support web search. /tldr will only see content the bot can fetch directly; questions that need fresh info from the open web may fall flat. Continue anyway?',
                model: warnModelId ?? '',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onConfirmWarn}>
              {t('common.continue', { defaultValue: 'Continue' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm delete */}
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('insight.byok.delete_title', { defaultValue: 'Remove BYOK config?' })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('insight.byok.delete_body', {
                defaultValue: 'Your provider key and model selection will be deleted. You can add them again any time.',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={removeConfig}>
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
