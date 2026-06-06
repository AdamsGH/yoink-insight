import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useGetIdentity } from '@refinedev/core'
import { BrainCircuit, ChevronDown, FileText, KeyRound, Link, LockKeyhole, MessageCircle, Pencil, Plus, RefreshCw, RotateCcw, Search, Trash2, X } from 'lucide-react'

import { insightApi, type ByokConfig, type InsightSettings, type InsightSettingsPatch, type TldrAlias, type TldrAliasInput } from '@insight/api/insight'
import ByokCard from './ByokCard'
import GithubLoginDialog from './GithubLoginDialog'
import { formatDate } from '@core/lib/utils'
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  Collapsible, CollapsibleContent, CollapsibleTrigger,
  Dialog, DialogActions, DialogContent, DialogHeader, DialogTitle,
  Field, FieldDescription, FieldLabel,
  Input, Label, Switch, Textarea,
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

const BUILTIN_ALIASES = ['max', 'nobullshit', 'noshit', 'tale']

interface BuiltinAliasDef {
  aliases: string[]
  target: string  // primary alias name used as target_alias
  desc: string
}

const BUILTIN_ALIAS_DEFS: BuiltinAliasDef[] = [
  { aliases: ['max'], target: 'max', desc: 'Thorough breakdown: all key points, technical details, bold headings.' },
  { aliases: ['nobullshit', 'noshit'], target: 'nobullshit', desc: 'Gruff, opinionated reviewer. Bold verdict on top, then pointed commentary on the actual claims. Calls out hype, acknowledges solid craft in the same voice.' },
  { aliases: ['tale'], target: 'tale', desc: 'Connected prose retelling, third person. 2-4 short paragraphs, no lists, no verdict, no wrap-up.' },
]

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

const DOMAIN_HINT = 'e.g. xda-developers.com, *.lwn.net, github.com/*'

function AliasDialog({
  open,
  initial,
  onClose,
  onSubmit,
}: {
  open: boolean
  initial?: TldrAlias
  onClose: () => void
  onSubmit: (body: TldrAliasInput) => Promise<void>
}) {
  const { t } = useTranslation()
  const [tags, setTags] = useState<string[]>([])
  const [domains, setDomains] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setTags(initial?.aliases ? initial.aliases.split(',').map(s => s.trim()).filter(Boolean) : [])
      setDomains(initial?.domains ? initial.domains.split(',').map(s => s.trim()).filter(Boolean) : [])
      setPrompt(initial?.prompt ?? '')
    }
  }, [open, initial])

  const builtinConflicts = tags.filter(tag => BUILTIN_ALIASES.includes(tag))
  const canSave = tags.length > 0 && prompt.trim().length > 0 && builtinConflicts.length === 0 && !saving

  const handleSubmit = async () => {
    if (!canSave) return
    setSaving(true)
    try {
      await onSubmit({
        aliases: tags.join(', '),
        prompt: prompt.trim(),
        domains: domains.length > 0 ? domains.join(', ') : null,
        target_alias: null,
      })
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
          <Field>
            <FieldLabel htmlFor="alias-prompt">{t('insight.alias_prompt_field', { defaultValue: 'Prompt instruction' })}</FieldLabel>
            <Textarea
              id="alias-prompt"
              className="min-h-[80px] resize-none text-sm"
              placeholder={t('insight.alias_prompt_placeholder', { defaultValue: 'e.g. Focus on technical details and code examples.' })}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </Field>
          <div className="space-y-1.5">
            <Label>{t('insight.alias_domains_field', { defaultValue: 'Auto-apply on domains (optional)' })}</Label>
            <TagInput tags={domains} onChange={setDomains} placeholder={DOMAIN_HINT} />
            <p className="text-xs text-muted-foreground">
              {t('insight.alias_domains_hint', { defaultValue: 'Matched against host[/path]. Use * as a glob: xda-developers.com/*, *.lwn.net.' })}
            </p>
          </div>
        </div>
        <DialogActions>
          <Button variant="outline" className="flex-1" onClick={onClose}>{t('common.cancel')}</Button>
          <Button className="flex-1" onClick={handleSubmit} disabled={!canSave}>
            {saving ? t('common.loading') : t('common.save')}
          </Button>
        </DialogActions>
      </DialogContent>
    </Dialog>
  )
}

// ---- Built-in domain binding dialog ----

function BuiltinBindDialog({
  open,
  def,
  existingRow,
  fullPrompt,
  onClose,
  onSubmit,
  onDelete,
}: {
  open: boolean
  def: BuiltinAliasDef | null
  existingRow?: TldrAlias
  fullPrompt?: string
  onClose: () => void
  onSubmit: (body: TldrAliasInput, existingId: number | null) => Promise<void>
  onDelete?: (id: number) => Promise<void>
}) {
  const { t } = useTranslation()
  const [domains, setDomains] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) {
      setDomains(existingRow?.domains ? existingRow.domains.split(',').map(s => s.trim()).filter(Boolean) : [])
    }
  }, [open, existingRow])

  if (!def) return null

  const handleSubmit = async () => {
    if (domains.length === 0) return
    setSaving(true)
    try {
      await onSubmit({
        target_alias: def.target,
        domains: domains.join(', '),
        aliases: null,
        prompt: null,
      }, existingRow?.id ?? null)
      onClose()
    } catch {
      // error handled by parent
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!existingRow || !onDelete) return
    setSaving(true)
    try {
      await onDelete(existingRow.id)
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
            <span>{t('insight.builtin_bind_title', { defaultValue: 'Bind domains to' })}</span>{' '}
            <span className="rounded bg-secondary px-1.5 py-0.5 font-mono text-sm text-secondary-foreground">
              {def.target}
            </span>
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <pre className="max-h-60 overflow-y-auto rounded-md border bg-muted px-3 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
            <code>{fullPrompt && fullPrompt.trim().length > 0 ? fullPrompt : def.desc}</code>
          </pre>
          <div className="space-y-1.5">
            <Label>{t('insight.alias_domains_field', { defaultValue: 'Auto-apply on domains' })}</Label>
            <TagInput tags={domains} onChange={setDomains} placeholder={DOMAIN_HINT} autoFocus />
            <p className="text-xs text-muted-foreground">
              {t('insight.alias_domains_hint', { defaultValue: 'Matched against host[/path]. Use * as a glob: xda-developers.com/*, *.lwn.net.' })}
            </p>
          </div>
        </div>
        <DialogActions>
          {existingRow && onDelete ? (
            <Button variant="outline" className="flex-1 text-destructive" onClick={handleDelete} disabled={saving}>
              {t('common.delete')}
            </Button>
          ) : (
            <Button variant="outline" className="flex-1" onClick={onClose} disabled={saving}>{t('common.cancel')}</Button>
          )}
          <Button className="flex-1" onClick={handleSubmit} disabled={domains.length === 0 || saving}>
            {saving ? t('common.loading') : t('common.save')}
          </Button>
        </DialogActions>
      </DialogContent>
    </Dialog>
  )
}

// ---- Prompt editor ----

function PromptEditor({
  command,
  icon,
  label,
  description,
  serverValue,
  defaultValue,
  edit,
  onChange,
}: {
  command: string
  icon: React.ReactNode
  label: string
  description?: string
  serverValue: string  // current override on server ('' if none)
  defaultValue: string  // built-in instruction
  edit: string | null  // null = unchanged in this session; string (incl. '') = local edit
  onChange: (value: string | null) => void
}) {
  const { t } = useTranslation()
  const fieldId = `prompt-${command}`
  const isOverridden = serverValue.trim().length > 0
  const displayValue = edit !== null ? edit : serverValue
  const isCustomNow = (edit ?? serverValue).trim().length > 0
  // Auto-expand when the user has a non-default prompt - they're more
  // likely to want to peek/edit it; defaults stay collapsed.
  const [open, setOpen] = useState(isCustomNow)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Field>
        <div className="flex items-center justify-between gap-2">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex items-center gap-1.5 text-left hover:text-foreground transition-colors"
            >
              <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform ${open ? '' : '-rotate-90'}`} />
              <span className="text-muted-foreground">{icon}</span>
              <span className="font-mono text-xs">{label}</span>
              {isCustomNow && (
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{t('insight.prompt_custom', { defaultValue: 'custom' })}</Badge>
              )}
            </button>
          </CollapsibleTrigger>
          {isCustomNow && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-1.5 text-[10px] text-muted-foreground hover:text-foreground"
                  onClick={() => onChange(isOverridden ? '' : null)}
                >
                  <RotateCcw className="h-3 w-3 mr-1" />
                  {t('insight.prompt_reset', { defaultValue: 'reset' })}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('insight.prompt_reset_hint', { defaultValue: 'Restore the built-in default on save.' })}</TooltipContent>
            </Tooltip>
          )}
        </div>
        <CollapsibleContent className="mt-1.5 space-y-1.5">
          {description && <FieldDescription>{description}</FieldDescription>}
          <Textarea
            id={fieldId}
            className="h-[400px] resize-none font-mono text-xs leading-relaxed"
            placeholder={defaultValue}
            value={displayValue}
            onChange={(e) => onChange(e.target.value)}
          />
        </CollapsibleContent>
      </Field>
    </Collapsible>
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
  const [githubLoginOpen, setGithubLoginOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const [aliases, setAliases] = useState<TldrAlias[]>([])
  const [loadingAliases, setLoadingAliases] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [aliasDialogOpen, setAliasDialogOpen] = useState(false)
  const [editAlias, setEditAlias] = useState<TldrAlias | undefined>(undefined)
  const [bindDialogDef, setBindDialogDef] = useState<BuiltinAliasDef | null>(null)

  const [useSearch, setUseSearch] = useState<boolean | null>(null)
  const [byok, setByok] = useState<ByokConfig | null>(null)
  // Local edits to prompt overrides. null = unchanged from server; '' (empty)
  // = user explicitly reset to default; non-empty = user-edited prompt.
  const [promptEdits, setPromptEdits] = useState<Record<string, string | null>>({})

  // Split rows: custom-alias rows (have keywords) vs pure domain-binding rows for built-ins.
  const builtinBindings = aliases.filter(a => a.target_alias && !a.aliases)
  const customAliases = aliases.filter(a => a.aliases)
  const bindingFor = (target: string) => builtinBindings.find(a => a.target_alias === target)

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
    Promise.all([
      insightApi.getSettings(),
      insightApi.getByok().catch(() => ({ data: null as ByokConfig | null })),
    ])
      .then(([res, byokRes]) => {
        setData(res.data)
        setLang(res.data.lang)
        setTldrModel(res.data.tldr_model ?? res.data.tldr_allowed_models[0] ?? '')
        setGithubToken('')
        setUseSearch(res.data.use_search)
        setPromptEdits({})
        setByok(byokRes.data)
        if (res.data.has_tldr_access) {
          if (res.data.has_tldr_gateway_access) {
            if (identity?.role === 'owner') {
              loadModels()
            } else {
              setAllModels(res.data.tldr_allowed_models)
            }
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
      const body: InsightSettingsPatch = { lang: lang ?? data?.lang }
      if (data?.has_tldr_gateway_access) {
        body.tldr_model = tldrModel ?? data?.tldr_model ?? null
        if (githubToken === '__clear__') {
          body.github_token = ''
        } else if (githubToken !== '') {
          body.github_token = githubToken
        }
      }
      if (data?.has_search_gateway_access && useSearch !== null && useSearch !== data.use_search) {
        body.use_search = useSearch
      }
      // Only send prompts that were touched in this session. Empty string =
      // explicit reset; non-empty = update; missing key = leave as-is.
      const promptsBody: Record<string, string | null> = {}
      for (const [cmd, val] of Object.entries(promptEdits)) {
        if (val === null) continue
        promptsBody[cmd] = val
      }
      if (Object.keys(promptsBody).length > 0) {
        body.prompts = promptsBody
      }
      const res = await insightApi.patchSettings(body)
      setData(res.data)
      setLang(res.data.lang)
      setTldrModel(res.data.tldr_model ?? res.data.tldr_allowed_models[0] ?? '')
      setGithubToken('')
      setUseSearch(res.data.use_search)
      setPromptEdits({})
      toast.success(t('common.saved'))
    } catch {
      toast.error(t('common.load_error'))
    } finally {
      setSaving(false)
    }
  }

  const handleCreateAlias = async (body: TldrAliasInput) => {
    try {
      await insightApi.createAlias(body)
      toast.success(t('common.saved'))
      loadAliases()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? t('common.load_error'))
      throw err
    }
  }

  const handleUpdateAlias = async (body: TldrAliasInput) => {
    if (!editAlias) return
    try {
      await insightApi.updateAlias(editAlias.id, body)
      toast.success(t('common.saved'))
      loadAliases()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? t('common.load_error'))
      throw err
    }
  }

  const handleBuiltinBindSubmit = async (body: TldrAliasInput, existingId: number | null) => {
    try {
      if (existingId !== null) {
        await insightApi.updateAlias(existingId, body)
      } else {
        await insightApi.createAlias(body)
      }
      toast.success(t('common.saved'))
      loadAliases()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? t('common.load_error'))
      throw err
    }
  }

  const handleBuiltinBindDelete = async (id: number) => {
    try {
      await insightApi.deleteAlias(id)
      toast.success(t('common.deleted', { defaultValue: 'Deleted' }))
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
  const tldrDirty = data !== null && data.has_tldr_gateway_access && tldrModel !== null && tldrModel !== (data.tldr_model ?? data.tldr_allowed_models[0] ?? '')
  const githubDirty = data !== null && data.has_tldr_gateway_access && githubToken !== ''
  const searchDirty = data !== null && data.has_search_gateway_access && useSearch !== null && useSearch !== data.use_search
  const promptsDirty = Object.values(promptEdits).some(v => v !== null)
  const dirty = langDirty || tldrDirty || githubDirty || searchDirty || promptsDirty

  const modelList = isOwner ? allModels : (data?.tldr_allowed_models ?? [])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="space-y-3">
        {/* AI access + Language */}
        <Card>
          <CardHeader className="px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                {data?.has_gemini_access
                  ? <BrainCircuit className="h-4 w-4 shrink-0 text-primary" />
                  : <LockKeyhole className="h-4 w-4 shrink-0 text-muted-foreground" />}
                {t('insight.settings_access_active', { defaultValue: 'AI Summary' })}
              </CardTitle>
              <span className={`text-xs font-medium ${data?.has_gemini_access ? 'text-primary' : 'text-muted-foreground'}`}>
                {data?.has_gemini_access
                  ? t('insight.access_active_short', { defaultValue: 'active' })
                  : t('insight.access_no_short', { defaultValue: 'no access' })}
              </span>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-2">
            <div className="divide-y divide-border">
              {!data?.has_gemini_access && !data?.has_tldr_access && (
                <div className="py-2">
                  <p className="text-xs text-muted-foreground">{t('insight.settings_no_access_body')}</p>
                </div>
              )}
              {(data?.has_gemini_access || data?.has_tldr_access) && (
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

        {/* AI Tools: per-user web search override (gateway-only) */}
        {data?.has_search_gateway_access && (
          <Card>
            <CardHeader className="px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Search className="h-4 w-4 shrink-0 text-primary" />
                  {t('insight.search_title', { defaultValue: 'AI Tools' })}
                </CardTitle>
                <span className="text-xs font-medium text-primary">
                  {t('insight.search_active_short', { defaultValue: 'available' })}
                </span>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              <div className="flex items-center justify-between gap-3 py-1">
                <div className="min-w-0 flex-1">
                  <p className="text-sm leading-snug">{t('insight.search_toggle_label', { defaultValue: 'Use web search engine' })}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground leading-snug">
                    {t('insight.search_toggle_hint', { defaultValue: 'Route /tldr, /summary and /about through the gateway answer engine. Better at scraping GitHub, Reddit, StackOverflow; can also resolve non-URL queries via web search.' })}
                  </p>
                </div>
                <Switch
                  checked={useSearch ?? data.use_search}
                  onCheckedChange={setUseSearch}
                />
              </div>
            </CardContent>
          </Card>
        )}

        {/* BYOK - only when admin enabled or the user already has a config saved */}
        {byok && (byok.enabled || byok.has_config) && (
          <ByokCard data={byok} onChange={setByok} />
        )}

        {/* TL;DR card. Shown when the user has a gateway-side grant (then
            it carries model + GitHub token), or when they have no grant at
            all (no-access state). BYOK-only users see their model in the
            BYOK card above, so this card is redundant for them and we
            hide it to avoid showing a gateway model that doesn't apply. */}
        {(data?.has_tldr_gateway_access || !data?.has_tldr_access) && (
        <Card>
          <CardHeader className="px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                {data?.has_tldr_gateway_access
                  ? <Link className="h-4 w-4 shrink-0 text-primary" />
                  : <LockKeyhole className="h-4 w-4 shrink-0 text-muted-foreground" />}
                {t('insight.tldr_title', { defaultValue: 'TL;DR' })}
              </CardTitle>
              <span className={`text-xs font-medium ${data?.has_tldr_gateway_access ? 'text-primary' : 'text-muted-foreground'}`}>
                {data?.has_tldr_gateway_access
                  ? t('insight.tldr_access_active', { defaultValue: 'active' })
                  : t('insight.tldr_no_access_short', { defaultValue: 'no access' })}
              </span>
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-2">
            <div className="space-y-0">

              {data?.has_tldr_gateway_access && (
                <div className="py-2 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm leading-snug">{t('insight.tldr_model_label', { defaultValue: 'LLM model' })}</p>
                    <Button
                      type="button" variant="ghost" size="sm" className="h-7 w-7 p-0 shrink-0"
                      disabled={loadingModels} onClick={loadModels}
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${loadingModels ? 'animate-spin' : ''}`} />
                    </Button>
                  </div>
                  <Combobox<string>
                    items={modelList}
                    itemToStringLabel={(m: string) => m}
                    itemToStringValue={(m: string) => m}
                  >
                    <ComboboxInput
                      value={tldrModel ?? data?.tldr_model ?? data?.tldr_allowed_models[0] ?? ''}
                      placeholder={t('insight.tldr_model_placeholder', { defaultValue: 'Select...' })}
                      className="h-8 text-xs font-mono w-full"
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
              )}

              {data?.has_tldr_gateway_access && (
                <div className="py-2 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <p className="text-sm leading-snug">{t('insight.github_token_label', { defaultValue: 'GitHub token' })}</p>
                      {data.github_token_set && githubToken === '' && (
                        <span className="text-xs text-green-500 font-medium">&#x2713;</span>
                      )}
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 px-2 text-xs"
                      onClick={() => setGithubLoginOpen(true)}
                    >
                      <KeyRound className="mr-1.5 h-3.5 w-3.5" />
                      {data.github_token_set
                        ? t('insight.github_login_relogin', { defaultValue: 'Re-link' })
                        : t('insight.github_login_button', { defaultValue: 'Sign in with GitHub' })}
                    </Button>
                  </div>
                  <div className="relative">
                    <Input
                      type="password"
                      placeholder={data.github_token_set && githubToken === ''
                        ? t('insight.github_token_placeholder_set', { defaultValue: 'New token to replace...' })
                        : 'ghp_...'}
                      value={githubToken === '__clear__' ? '' : githubToken}
                      onChange={(e) => setGithubToken(e.target.value)}
                      className="h-8 font-mono text-xs pr-9"
                    />
                    {data.github_token_set && githubToken === '' && (
                      <button
                        type="button"
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-destructive transition-colors"
                        onClick={() => setGithubToken('__clear__')}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  {githubToken === '__clear__' && (
                    <p className="text-xs text-destructive">{t('insight.github_token_will_clear', { defaultValue: 'Token will be removed on save.' })}</p>
                  )}
                  <p className="text-xs text-muted-foreground whitespace-nowrap">For private repos &amp; rate limits</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
        )}

        <GithubLoginDialog
          open={githubLoginOpen}
          onClose={() => setGithubLoginOpen(false)}
          onSuccess={() => {
            // Re-pull /insight/settings/me so github_token_set flips to true
            // without requiring a full page reload.
            void insightApi.getSettings().then((res) => {
              setData(res.data)
              setGithubToken('')
            }).catch(() => {})
          }}
        />

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

        {/* Default Prompts */}
        {data && (data.has_gemini_access || data.has_tldr_access) && (
          <Card>
            <CardHeader className="px-4 py-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-4 w-4 shrink-0 text-primary" />
                {t('insight.prompts_title', { defaultValue: 'Default Prompts' })}
              </CardTitle>
              <p className="text-xs text-muted-foreground leading-snug">
                {t('insight.prompts_hint', { defaultValue: 'Replace the built-in instruction for each command. Empty = use the default.' })}
              </p>
            </CardHeader>
            <CardContent className="px-4 pb-3 space-y-3">
              {data.has_gemini_access && (
                <PromptEditor
                  command="summary"
                  icon={<FileText className="h-3.5 w-3.5" />}
                  label={t('insight.prompt_summary_label', { defaultValue: '/summary' })}
                  description={t('insight.prompt_summary_desc', { defaultValue: 'Bullet-list summary of a YouTube video.' })}
                  serverValue={data.prompts.summary ?? ''}
                  defaultValue={data.prompt_defaults.summary ?? ''}
                  edit={promptEdits.summary ?? null}
                  onChange={(v) => setPromptEdits(prev => ({ ...prev, summary: v }))}
                />
              )}
              {data.has_gemini_access && (
                <PromptEditor
                  command="about"
                  icon={<MessageCircle className="h-3.5 w-3.5" />}
                  label={t('insight.prompt_about_label', { defaultValue: '/about' })}
                  description={t('insight.prompt_about_desc', { defaultValue: 'Short 2-3 sentence pitch of a YouTube video.' })}
                  serverValue={data.prompts.about ?? ''}
                  defaultValue={data.prompt_defaults.about ?? ''}
                  edit={promptEdits.about ?? null}
                  onChange={(v) => setPromptEdits(prev => ({ ...prev, about: v }))}
                />
              )}
              {data.has_tldr_access && (
                <PromptEditor
                  command="tldr"
                  icon={<Link className="h-3.5 w-3.5" />}
                  label={t('insight.prompt_tldr_label', { defaultValue: '/tldr (default)' })}
                  description={t('insight.prompt_tldr_desc', { defaultValue: 'Default for /tldr without alias or question. Aliases stay independent.' })}
                  serverValue={data.prompts.tldr ?? ''}
                  defaultValue={data.prompt_defaults.tldr ?? ''}
                  edit={promptEdits.tldr ?? null}
                  onChange={(v) => setPromptEdits(prev => ({ ...prev, tldr: v }))}
                />
              )}
            </CardContent>
          </Card>
        )}

        {/* Aliases */}
        {data?.has_tldr_access && (
          <Card>
            <CardHeader className="px-4 py-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base font-medium text-muted-foreground">
                  {t('insight.aliases_hint', { defaultValue: 'Use /tldr <url> <alias> to apply.' })}
                </CardTitle>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button size="sm" variant="outline" className="h-7 w-7 p-0 shrink-0" onClick={() => { setEditAlias(undefined); setAliasDialogOpen(true) }}>
                      <Plus className="h-3.5 w-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('insight.alias_add_title', { defaultValue: 'Add alias' })}</TooltipContent>
                </Tooltip>
              </div>
            </CardHeader>
            <CardContent className="p-0 pb-2">
              <div className="divide-y divide-border">
                {BUILTIN_ALIAS_DEFS.map((def) => {
                  const binding = bindingFor(def.target)
                  const boundDomains = binding?.domains?.split(',').map(s => s.trim()).filter(Boolean) ?? []
                  return (
                    <div key={def.target} className="flex items-start gap-3 px-4 py-2.5">
                      <div className="flex-1 min-w-0 space-y-0.5">
                        <div className="flex flex-wrap gap-1">
                          {def.aliases.map(tag => (
                            <Badge key={tag} variant="outline" className="font-mono text-xs px-1.5 py-0 text-muted-foreground">{tag}</Badge>
                          ))}
                          <span className="text-[10px] text-muted-foreground/50 self-center">built-in</span>
                        </div>
                        <p className="text-xs text-muted-foreground line-clamp-2">{def.desc}</p>
                        {boundDomains.length > 0 && (
                          <div className="flex flex-wrap gap-1 pt-0.5">
                            {boundDomains.map(d => (
                              <Badge key={d} variant="secondary" className="font-mono text-[10px] px-1.5 py-0">{d}</Badge>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="flex gap-1 shrink-0 pt-0.5">
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => setBindDialogDef(def)}>
                              <Link className="h-3.5 w-3.5" />
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>{t('insight.builtin_bind_title', { defaultValue: 'Bind domains to' })} {def.target}</TooltipContent>
                        </Tooltip>
                      </div>
                    </div>
                  )
                })}
              </div>
              {loadingAliases ? (
                <div className="px-4 py-3 text-xs text-muted-foreground border-t border-border">{t('common.loading')}</div>
              ) : customAliases.length === 0 ? (
                <div className="px-4 py-3 text-center text-xs text-muted-foreground border-t border-border">
                  {t('insight.aliases_empty', { defaultValue: 'No custom aliases yet.' })}
                </div>
              ) : (
                <div className="divide-y divide-border border-t border-border">
                  {customAliases.map((a) => {
                    const aliasTags = a.aliases?.split(',').map(s => s.trim()).filter(Boolean) ?? []
                    const domainTags = a.domains?.split(',').map(s => s.trim()).filter(Boolean) ?? []
                    return (
                      <div key={a.id} className="flex items-start gap-3 px-4 py-3">
                        <div className="flex-1 min-w-0 space-y-0.5">
                          <div className="flex flex-wrap gap-1">
                            {aliasTags.map(tag => (
                              <Badge key={tag} variant="secondary" className="font-mono text-xs px-1.5 py-0">{tag}</Badge>
                            ))}
                          </div>
                          {a.prompt && <p className="text-xs text-muted-foreground line-clamp-2">{a.prompt}</p>}
                          {domainTags.length > 0 && (
                            <div className="flex flex-wrap gap-1 pt-0.5">
                              {domainTags.map(d => (
                                <Badge key={d} variant="outline" className="font-mono text-[10px] px-1.5 py-0 text-muted-foreground">{d}</Badge>
                              ))}
                            </div>
                          )}
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
                    )
                  })}
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
        <BuiltinBindDialog
          open={bindDialogDef !== null}
          def={bindDialogDef}
          existingRow={bindDialogDef ? bindingFor(bindDialogDef.target) : undefined}
          fullPrompt={bindDialogDef ? data?.alias_defaults?.[bindDialogDef.target] : undefined}
          onClose={() => setBindDialogDef(null)}
          onSubmit={handleBuiltinBindSubmit}
          onDelete={handleBuiltinBindDelete}
        />
      </div>
    </TooltipProvider>
  )
}
