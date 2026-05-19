import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, X } from 'lucide-react'

import { insightApi, type GatewayModel, type TldrConfig } from '@insight/api/insight'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label,
  Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList,
} from '@ui'
import { toast } from '@core/components/ui/toast'

export default function TldrConfigPage() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<TldrConfig | null>(null)
  const [allModels, setAllModels] = useState<GatewayModel[]>([])
  const [allowed, setAllowed] = useState<string[]>([])
  const [defaultModel, setDefaultModel] = useState('')
  const [gatewayUrl, setGatewayUrl] = useState('')
  const [gatewayKey, setGatewayKey] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string; model_count?: number } | null>(null)
  const [refreshingModels, setRefreshingModels] = useState(false)

  useEffect(() => {
    Promise.all([insightApi.getTldrConfig(), insightApi.listModels()])
      .then(([cfgRes, modelsRes]) => {
        setConfig(cfgRes.data)
        setAllowed(cfgRes.data.allowed_models)
        setDefaultModel(cfgRes.data.default_model)
        setGatewayUrl(cfgRes.data.gateway_base_url)
        setGatewayKey(cfgRes.data.gateway_api_key)
        setAllModels(modelsRes.data)
      })
      .catch(() => toast.error(t('common.load_error')))
      .finally(() => setLoading(false))
  }, [t])

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await insightApi.testGateway(gatewayUrl, gatewayKey || undefined)
      setTestResult(res.data)
      if (res.data.ok) {
        const modelsRes = await insightApi.listModels()
        setAllModels(modelsRes.data)
      }
    } catch {
      setTestResult({ ok: false, error: 'Request failed' })
    } finally {
      setTesting(false)
    }
  }

  const refreshModels = async () => {
    setRefreshingModels(true)
    try {
      const res = await insightApi.listModels()
      setAllModels(res.data)
      toast.success(`${res.data.length} models loaded`)
    } catch {
      toast.error(t('common.load_error'))
    } finally {
      setRefreshingModels(false)
    }
  }

  const addModel = (m: GatewayModel | null) => {
    if (!m || allowed.includes(m.id)) return
    setAllowed((prev) => [...prev, m.id])
    if (!defaultModel) setDefaultModel(m.id)
  }

  const removeModel = (id: string) => {
    const next = allowed.filter((m) => m !== id)
    setAllowed(next)
    if (defaultModel === id) setDefaultModel(next[0] ?? '')
  }

  const save = async () => {
    if (!allowed.length) {
      toast.error(t('insight.tldr_config_empty_error', { defaultValue: 'Add at least one model.' }))
      return
    }
    if (!defaultModel || !allowed.includes(defaultModel)) {
      toast.error(t('insight.tldr_config_default_error', { defaultValue: 'Default model must be in the allowed list.' }))
      return
    }
    if (!gatewayUrl) {
      toast.error(t('insight.tldr_config_url_error', { defaultValue: 'Gateway URL is required.' }))
      return
    }
    setSaving(true)
    try {
      const res = await insightApi.patchTldrConfig({
        allowed_models: allowed,
        default_model: defaultModel,
        gateway_base_url: gatewayUrl,
        gateway_api_key: gatewayKey,
      })
      setConfig(res.data)
      setAllowed(res.data.allowed_models)
      setDefaultModel(res.data.default_model)
      setGatewayUrl(res.data.gateway_base_url)
      setGatewayKey(res.data.gateway_api_key)
      toast.success(t('common.saved'))
    } catch {
      toast.error(t('common.load_error'))
    } finally {
      setSaving(false)
    }
  }

  const available = allModels.filter((m) => !allowed.includes(m.id))
  const allowedModels = allModels.filter((m) => allowed.includes(m.id))

  if (loading) {
    return <div className="flex justify-center py-24 text-muted-foreground">{t('common.loading')}</div>
  }

  const dirty = config !== null && (
    JSON.stringify(allowed) !== JSON.stringify(config.allowed_models) ||
    defaultModel !== config.default_model ||
    gatewayUrl !== config.gateway_base_url ||
    gatewayKey !== config.gateway_api_key
  )

  return (
    <div className="space-y-3">
      {/* Gateway connection */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            {t('insight.tldr_gateway_title', { defaultValue: 'Gateway' })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              {t('insight.tldr_gateway_url_label', { defaultValue: 'Base URL' })}
            </Label>
            <Input
              value={gatewayUrl}
              onChange={(e) => { setGatewayUrl(e.target.value); setTestResult(null) }}
              placeholder="http://10.145.0.50:4060"
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              {t('insight.tldr_gateway_key_label', { defaultValue: 'API key' })}
            </Label>
            <Input
              value={gatewayKey}
              onChange={(e) => { setGatewayKey(e.target.value); setTestResult(null) }}
              placeholder={t('insight.tldr_gateway_key_placeholder', { defaultValue: 'Leave empty if not required' })}
              type="password"
              className="font-mono text-xs"
            />
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={testConnection}
              disabled={testing || !gatewayUrl}
            >
              {testing ? t('common.loading') : t('insight.tldr_test_btn', { defaultValue: 'Test connection' })}
            </Button>
            {testResult && (
              <span className={`text-xs ${testResult.ok ? 'text-green-600' : 'text-destructive'}`}>
                {testResult.ok
                  ? `OK - ${testResult.model_count ?? 0} models`
                  : testResult.error}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Model config */}
      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            {t('insight.tldr_config_title', { defaultValue: 'Models' })}
          </CardTitle>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={refreshModels}
            disabled={refreshingModels}
            title={t('insight.tldr_refresh_models', { defaultValue: 'Refresh from gateway' })}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshingModels ? 'animate-spin' : ''}`} />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              {t('insight.tldr_config_allowed_label', { defaultValue: 'Models users can choose from' })}
            </Label>
            <div className="flex flex-wrap gap-1.5 min-h-8">
              {allowed.map((m) => (
                <Badge key={m} variant="secondary" className="font-mono text-xs gap-1 pr-1">
                  {m}
                  <button
                    onClick={() => removeModel(m)}
                    className="ml-0.5 rounded hover:text-destructive"
                    disabled={allowed.length <= 1}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
            {available.length > 0 && (
              <Combobox
                value={null}
                onValueChange={addModel}
                items={available}
                itemToStringLabel={(m: GatewayModel) => m.id}
                itemToStringValue={(m: GatewayModel) => m.id}
              >
                <ComboboxInput
                  placeholder={t('insight.tldr_config_add_placeholder', { defaultValue: 'Add model...' })}
                  className="font-mono text-xs"
                />
                <ComboboxContent>
                  <ComboboxEmpty>{t('common.no_results', { defaultValue: 'No models found.' })}</ComboboxEmpty>
                  <ComboboxList>
                    {(m: GatewayModel) => (
                      <ComboboxItem key={m.id} value={m} className="font-mono text-xs">
                        {m.id}
                      </ComboboxItem>
                    )}
                  </ComboboxList>
                </ComboboxContent>
              </Combobox>
            )}
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">
              {t('insight.tldr_config_default_label', { defaultValue: 'Default model (for new users)' })}
            </Label>
            <Combobox
              value={allowedModels.find((m) => m.id === defaultModel) ?? null}
              onValueChange={(m: GatewayModel | null) => m && setDefaultModel(m.id)}
              items={allowedModels}
              itemToStringLabel={(m: GatewayModel) => m.id}
              itemToStringValue={(m: GatewayModel) => m.id}
            >
              <ComboboxInput className="font-mono text-xs" />
              <ComboboxContent>
                <ComboboxEmpty>{t('common.no_results', { defaultValue: 'No models.' })}</ComboboxEmpty>
                <ComboboxList>
                  {(m: GatewayModel) => (
                    <ComboboxItem key={m.id} value={m} className="font-mono text-xs">
                      {m.id}
                    </ComboboxItem>
                  )}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
          </div>
        </CardContent>
      </Card>

      <Button onClick={save} disabled={saving || !dirty} size="sm" className="w-full">
        {saving ? t('common.saving') : t('common.save')}
      </Button>
    </div>
  )
}
