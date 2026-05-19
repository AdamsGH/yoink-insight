import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useGetIdentity } from '@refinedev/core'
import { BrainCircuit, Link, LockKeyhole, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react'

import { insightApi, type InsightSettings, type TldrAlias } from '@insight/api/insight'
import { formatDate } from '@core/lib/utils'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
  Input, Label,
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
  Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList,
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@ui'
import { toast } from '@core/components/ui/toast'
import type { User } from '@core/types/api'

const LANG_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'ru', label: 'Русский' },
] as const

const BUILTIN_ALIASES = ['max', 'nobullshit', 'noshit']

// ---- Tag input ----

function TagInput({
  tags,
  onChange,
  placeholder,
  autoFocus,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  autoFocus?: boolean
}) {
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const commit = (raw: string) => {
    const tag = raw.trim().toLowerCase()
    if (tag && !tags.includes(tag)) onChange([...tags, tag])
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === ',' || e.key === 'Enter') {
      e.preventDefault()
      commit(input)
    } else if (e.key === 'Backspace' && !input && tags.length > 0) {
      onChange(tags.slice(0, -1))
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    if (val.endsWith(',')) {
      commit(val.slice(0, -1))
    } else {
      setInput(val)
    }
  }

  const remove = (tag: string) => {
    onChange(tags.filter(t => t !== tag))
    inputRef.current?.focus()
  }

  return (
    <div
      className="flex flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2.5 py-1.5 min-h-9 cursor-text focus-within:ring-1 focus-within:ring-ring"
      onClick={() => inputRef.current?.focus()}
    >
      {tags.map(tag => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded-full border border-transparent bg-secondary text-secondary-foreground px-2 py-0.5 text-xs font-mono font-semibold"
        >
          {tag}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); remove(tag) }}
            className="text-secondary-foreground/60 hover:text-secondary-foreground transition-colors"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={input}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={tags.length === 0 ? placeholder : ''}
        autoFocus={autoFocus}
        className="flex-1 min-w-[80px] bg-transparent text-xs font-mono outline-none placeholder:text-muted-foreground"
      />
    </div>
  )
}

// ---- Alias dialog ----

function AliasDialog({
  open,
  initial,
  onClose,
  onSubmit,
}: {
  open: boolean
  initial?: TldrAlias
  onClose: () => void
  onSubmit: (aliases: string, prompt: string) => Promise<void>
}) {
  const { t } = useTranslation()
  const [tags, setTags] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setTags(initial?.aliases ? initial.aliases.split(',').map(s => s.trim()).filter(Boolean) : [])
      setPrompt(initial?.prompt ?? '')
    }
  }, [open, initial])

  const builtinConflicts = tags.filter(t => BUILTIN_ALIASES.includes(t))
  const canSave = tags.length > 0 && prompt.trim().length > 0 && builtinConflicts.length === 0 && !saving

  const handleSubmit = async () => {
    if (!canSave) return
    setSaving(true)
    try {
      await onSubmit(tags.join(', '), prompt.trim())
      onClose()
    } catch {
      // error handled by parent
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            {initial
              ? t('insight.alias_edit_title', { defaultValue: 'Edit alias' })
              : t('insight.alias_add_title', { defaultValue: 'Add alias' })}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>{t('insight.alias_field', { defaultValue: 'Aliases' })}</Label>
            <TagInput
              tags={tags}
              onChange={setTags}
              placeholder="deep, brief, tech ..."
              autoFocus={!initial}
            />
            {builtinConflicts.length > 0 && (
              <p className="text-xs text-destructive">
                {builtinConflicts.join(', ')} {t('insight.alias_builtin_conflict', { defaultValue: 'is a built-in alias and cannot be overridden.' })}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              {t('insight.alias_field_hint', { defaultValue: 'Type and press comma or Enter to add. Each word triggers the same prompt.' })}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>{t('insight.alias_prompt_field', { defaultValue: 'Prompt instruction' })}</Label>
            <textarea
              className="w-full min-h-[80px] rounded-md border border-input bg-background px-3 py-2 text-sm resize-y focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder={t('insight.alias_prompt_placeholder', { defaultValue: 'e.g. Focus on technical details and code examples.' })}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter className="flex-row gap-2 sm:space-x-0">
          <Button variant="outline" className="flex-1" onClick={onClose}>{t('common.cancel')}</Button>
          <Button className="flex-1" onClick={handleSubmit} disabled={!canSave}>
            {saving ? t('common.loading') : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---- Main page ----

export default function InsightSettingsPage() {
  const { t } = useTranslation()
  const { data: identity } = useGetIdentity<User>()
  const isOwner = identity?.role === 'owner'

  const [data, setData] = useState<InsightSettings | null>(null)
  const [lang, setLang] = useState<string | null>(null)
  const [tldrModel, setTldrModel] = useState<string | null>(null)
  const [allModels, setAllModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [githubToken, setGithubToken] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const [aliases, setAliases] = useState<TldrAlias[]>([])
  const [loadingAliases, setLoadingAliases] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [aliasDialogOpen, setAliasDialogOpen] = useState(false)
  const [editAlias, setEditAlias] = useState<TldrAlias | undefined>(undefined)

  const loadModels = async () => {
    setLoadingModels(true)
    try {
      const res = await insightApi.listModels()
      setAllModels(res.data.map((m) => m.id))
    } catch {
      toast.error(t('common.load_error'))
    } finally {
      setLoadingModels(false)
    }
  }

  const loadAliases = useCallback(() => {
    setLoadingAliases(true)
    insightApi.listAliases()
      .then((res) => setAliases(res.data))
      .catch(() => toast.error(t('common.load_error')))
      .finally(() => setLoadingAliases(false))
  }, [t])

  useEffect(() => {
    insightApi
      .getSettings()
      .then((res) => {
        setData(res.data)
        setLang(res.data.lang)
        setTldrModel(res.data.tldr_model ?? res.data.tldr_allowed_models[0] ?? '')
        setGithubToken('')
        if (res.data.has_tldr_access) {
          if (identity?.role === 'owner') {
            loadModels()
          } else {
            setAllModels(res.data.tldr_allowed_models)
          }
          loadAliases()
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity?.role])

  const save = async () => {
    setSaving(true)
    try {
      const body: { lang?: string; tldr_model?: string | null; github_token?: string | null } = { lang: lang ?? data?.lang }
      if (data?.has_tldr_access) {
        body.tldr_model = tldrModel ?? data?.tldr_model ?? null
        if (githubToken === '__clear__') {
          body.github_token = ''
        } else if (githubToken !== '') {
          body.github_token = githubToken
        }
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

  const handleCreateAlias = async (aliases: string, prompt: string) => {
    try {
      await insightApi.createAlias(aliases, prompt)
      toast.success(t('common.saved'))
      loadAliases()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? t('common.load_error'))
      throw err
    }
  }

  const handleUpdateAlias = async (aliases: string, prompt: string) => {
    if (!editAlias) return
    try {
      await insightApi.updateAlias(editAlias.id, aliases, prompt)
      toast.success(t('common.saved'))
      loadAliases()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? t('common.load_error'))
      throw err
    }
  }

  const handleDeleteAlias = async (a: TldrAlias) => {
    setDeletingId(a.id)
    try {
      await insightApi.deleteAlias(a.id)
      toast.success(t('common.deleted', { defaultValue: 'Deleted' }))
      loadAliases()
    } catch {
      toast.error(t('common.load_error'))
    } finally {
      setDeletingId(null)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-24 text-muted-foreground">{t('common.loading')}</div>
  }

  const langDirty = data !== null && lang !== null && lang !== data.lang
  const tldrDirty = data !== null && data.has_tldr_access && tldrModel !== null && tldrModel !== (data.tldr_model ?? data.tldr_allowed_models[0] ?? '')
  const githubDirty = data !== null && data.has_tldr_access && githubToken !== ''
  const dirty = langDirty || tldrDirty || githubDirty

  const modelList = isOwner ? allModels : (data?.tldr_allowed_models ?? [])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="space-y-3">
        {/* AI access + Language */}
        <Card>
          <CardHeader className="px-4 py-3">
            <CardTitle className="flex items-center gap-2 text-base">
              {data?.has_access
                ? <BrainCircuit className="h-4 w-4 shrink-0 text-primary" />
                : <LockKeyhole className="h-4 w-4 shrink-0 text-muted-foreground" />}
              {data?.has_access
                ? t('insight.settings_access_active', { defaultValue: 'AI Summary' })
                : t('insight.settings_no_access_title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-2">
            <div className="divide-y divide-border">
              <div className="py-2">
                <p className="text-xs text-muted-foreground">
                  {data?.has_access && data.granted_at
                    ? t('insight.settings_access_granted', { date: formatDate(data.granted_at) })
                    : t('insight.settings_no_access_body')}
                </p>
              </div>
              {data?.has_access && (
                <div className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-snug">{t('insight.settings_lang_label')}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground leading-snug">{t('insight.settings_lang_hint')}</p>
                  </div>
                  <Select value={lang ?? data?.lang ?? 'en'} onValueChange={setLang}>
                    <SelectTrigger className="h-8 text-xs w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LANG_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value} className="text-xs">{o.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* TL;DR */}
        <Card>
          <CardHeader className="px-4 py-3">
            <CardTitle className="flex items-center gap-2 text-base">
              {data?.has_tldr_access
                ? <Link className="h-4 w-4 shrink-0 text-primary" />
                : <LockKeyhole className="h-4 w-4 shrink-0 text-muted-foreground" />}
              {t('insight.tldr_title', { defaultValue: 'TL;DR' })}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-2">
            <div className="divide-y divide-border">
              <div className="py-2">
                <p className="text-xs text-muted-foreground">
                  {data?.has_tldr_access
                    ? t('insight.tldr_access_active', { defaultValue: 'Access active - summarise any URL with /tldr' })
                    : t('insight.tldr_no_access', { defaultValue: 'No TL;DR access. Ask an admin.' })}
                </p>
              </div>

              {data?.has_tldr_access && (
                <div className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-snug">{t('insight.tldr_model_label', { defaultValue: 'LLM model' })}</p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button
                      type="button" variant="ghost" size="sm" className="h-7 w-7 p-0"
                      disabled={loadingModels} onClick={loadModels}
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${loadingModels ? 'animate-spin' : ''}`} />
                    </Button>
                    <Combobox<string>
                      items={modelList}
                      itemToStringLabel={(m: string) => m}
                      itemToStringValue={(m: string) => m}
                    >
                      <ComboboxInput
                        value={tldrModel ?? data?.tldr_model ?? data?.tldr_allowed_models[0] ?? ''}
                        placeholder={t('insight.tldr_model_placeholder', { defaultValue: 'Select...' })}
                        className="h-8 text-xs font-mono w-44"
                      />
                      <ComboboxContent>
                        <ComboboxEmpty>{t('common.no_results', { defaultValue: 'No models found' })}</ComboboxEmpty>
                        <ComboboxList>
                          {(item) => (
                            <ComboboxItem key={item} value={item} onSelect={() => setTldrModel(item)} className="font-mono text-xs">
                              {item}
                            </ComboboxItem>
                          )}
                        </ComboboxList>
                      </ComboboxContent>
                    </Combobox>
                  </div>
                </div>
              )}

              {data?.has_tldr_access && (
                <div className="py-2 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <p className="text-sm leading-snug">{t('insight.github_token_label', { defaultValue: 'GitHub token' })}</p>
                    {data.github_token_set && githubToken === '' && (
                      <span className="text-xs text-green-500 font-medium">&#x2713; saved</span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      type="password"
                      placeholder={data.github_token_set && githubToken === ''
                        ? t('insight.github_token_placeholder_set', { defaultValue: 'Enter new token to replace' })
                        : 'ghp_...'}
                      value={githubToken === '__clear__' ? '' : githubToken}
                      onChange={(e) => setGithubToken(e.target.value)}
                      className="h-8 font-mono text-xs flex-1"
                    />
                    {data.github_token_set && githubToken === '' && (
                      <Button type="button" variant="outline" size="sm" className="h-8 text-xs shrink-0"
                        onClick={() => setGithubToken('__clear__')}>
                        {t('common.clear', { defaultValue: 'Clear' })}
                      </Button>
                    )}
                  </div>
                  {githubToken === '__clear__' && (
                    <p className="text-xs text-destructive">{t('insight.github_token_will_clear', { defaultValue: 'Token will be removed on save.' })}</p>
                  )}
                  <p className="text-xs text-muted-foreground">{t('insight.github_token_hint', { defaultValue: 'For private repos and to avoid GitHub rate limits.' })}</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Save */}
        {dirty && (
          <Button
            onClick={save}
            disabled={saving}
            size="sm"
            className="w-full"
          >
            {saving ? t('common.saving') : t('common.save')}
          </Button>
        )}

        {/* Aliases */}
        {data?.has_tldr_access && (
          <Card>
            <CardHeader className="px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-sm font-medium">
                  {t('insight.aliases_title', { defaultValue: '/tldr aliases' })}
                </CardTitle>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button size="icon" className="h-7 w-7 shrink-0" onClick={() => { setEditAlias(undefined); setAliasDialogOpen(true) }}>
                      <Plus className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('insight.alias_add_title', { defaultValue: 'Add alias' })}</TooltipContent>
                </Tooltip>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {t('insight.aliases_hint', { defaultValue: 'Use /tldr <url> <alias> to apply. Built-in: max, nobullshit.' })}
              </p>
            </CardHeader>
            <CardContent className="p-0 pb-2">
              {loadingAliases ? (
                <div className="px-4 py-3 text-xs text-muted-foreground">{t('common.loading')}</div>
              ) : aliases.length === 0 ? (
                <div className="px-4 py-4 text-center text-xs text-muted-foreground">
                  {t('insight.aliases_empty', { defaultValue: 'No custom aliases yet.' })}
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {aliases.map((a) => (
                    <div key={a.id} className="flex items-start gap-3 px-4 py-3">
                      <div className="flex-1 min-w-0 space-y-0.5">
                        <div className="flex flex-wrap gap-1">
                          {a.aliases.split(',').map(s => s.trim()).filter(Boolean).map(tag => (
                            <Badge key={tag} variant="secondary" className="font-mono text-xs px-1.5 py-0">{tag}</Badge>
                          ))}
                        </div>
                        <p className="text-xs text-muted-foreground line-clamp-2">{a.prompt}</p>
                        <p className="text-xs text-muted-foreground/60">{formatDate(a.created_at)}</p>
                      </div>
                      <div className="flex gap-1 shrink-0 pt-0.5">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => { setEditAlias(a); setAliasDialogOpen(true) }}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>{t('common.edit')}</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                              disabled={deletingId === a.id}
                              onClick={() => handleDeleteAlias(a)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>{t('common.delete')}</TooltipContent>
                        </Tooltip>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <AliasDialog
          open={aliasDialogOpen}
          initial={editAlias}
          onClose={() => { setAliasDialogOpen(false); setEditAlias(undefined) }}
          onSubmit={editAlias ? handleUpdateAlias : handleCreateAlias}
        />
      </div>
    </TooltipProvider>
  )
}
