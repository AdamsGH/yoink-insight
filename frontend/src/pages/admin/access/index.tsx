import { useEffect, useRef, useState } from 'react'

import { apiClient } from '@core/lib/api-client'
import { formatDate } from '@core/lib/utils'
import type { InsightAccess, UserLookupResult } from '@insight/types'
import { Button } from '@core/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@core/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@core/components/ui/dialog'
import { Input } from '@core/components/ui/input'
import { Label } from '@core/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@core/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@core/components/ui/sheet'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@core/components/ui/table'
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

function displayUser(item: InsightAccess): string {
  if (item.username) return `@${item.username}`
  if (item.first_name) return item.first_name
  return String(item.user_id)
}

function displayGrantedBy(item: InsightAccess): string {
  if (item.granted_by_username) return `@${item.granted_by_username}`
  return String(item.granted_by)
}

function langLabel(value: string): string {
  return LANG_OPTIONS.find((o) => o.value === value)?.label ?? value
}

export default function InsightAccessPage() {
  const [items, setItems] = useState<InsightAccess[]>([])
  const [loading, setLoading] = useState(true)

  // Sheet (mobile detail + edit)
  const [sheet, setSheet] = useState<InsightAccess | null>(null)
  const [sheetLang, setSheetLang] = useState('en')
  const [sheetSaving, setSheetSaving] = useState(false)

  // Inline lang edit (desktop)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editLang, setEditLang] = useState('en')
  const [inlineSaving, setInlineSaving] = useState(false)

  // Grant dialog
  const [grantOpen, setGrantOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<UserLookupResult[]>([])
  const [selectedUser, setSelectedUser] = useState<UserLookupResult | null>(null)
  const [grantLang, setGrantLang] = useState('en')
  const [granting, setGranting] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [revoking, setRevoking] = useState<number | null>(null)

  const load = () => {
    setLoading(true)
    apiClient
      .get<InsightAccess[]>('/insight/access')
      .then((r) => setItems(r.data))
      .catch(() => toast.error('Failed to load access list'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  // Debounced user lookup
  useEffect(() => {
    if (!grantOpen) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 1) { setSuggestions([]); return }
    debounceRef.current = setTimeout(() => {
      apiClient
        .get<UserLookupResult[]>(`/insight/access/lookup?q=${encodeURIComponent(query)}`)
        .then((r) => setSuggestions(r.data))
        .catch(() => setSuggestions([]))
    }, 300)
  }, [query, grantOpen])

  // Grant dialog
  const openGrant = () => {
    setQuery('')
    setSuggestions([])
    setSelectedUser(null)
    setGrantLang('en')
    setGrantOpen(true)
  }

  const selectSuggestion = (u: UserLookupResult) => {
    setSelectedUser(u)
    setQuery(u.username ? `@${u.username}` : u.first_name ?? String(u.id))
    setSuggestions([])
  }

  const submitGrant = async () => {
    if (!selectedUser) { toast.error('Select a user first'); return }
    setGranting(true)
    try {
      await apiClient.post(`/insight/access/${selectedUser.id}`, { lang: grantLang })
      toast.success(`Access granted to ${selectedUser.username ? '@' + selectedUser.username : selectedUser.id}`)
      setGrantOpen(false)
      load()
    } catch {
      toast.error('Failed to grant access')
    } finally {
      setGranting(false)
    }
  }

  // Desktop inline edit
  const startEdit = (item: InsightAccess) => {
    setEditingId(item.user_id)
    setEditLang(item.lang)
  }

  const cancelEdit = () => setEditingId(null)

  const saveInline = async (userId: number) => {
    setInlineSaving(true)
    try {
      await apiClient.patch(`/insight/access/${userId}`, { lang: editLang })
      toast.success('Language updated')
      setEditingId(null)
      load()
    } catch {
      toast.error('Failed to update language')
    } finally {
      setInlineSaving(false)
    }
  }

  // Mobile sheet edit
  const openSheet = (item: InsightAccess) => {
    setSheet(item)
    setSheetLang(item.lang)
  }

  const saveSheet = async () => {
    if (!sheet) return
    setSheetSaving(true)
    try {
      await apiClient.patch(`/insight/access/${sheet.user_id}`, { lang: sheetLang })
      toast.success('Language updated')
      setSheet(null)
      load()
    } catch {
      toast.error('Failed to update language')
    } finally {
      setSheetSaving(false)
    }
  }

  const revoke = async (userId: number, label: string, fromSheet = false) => {
    setRevoking(userId)
    if (fromSheet) setSheet(null)
    try {
      await apiClient.delete(`/insight/access/${userId}`)
      toast.success(`Access revoked for ${label}`)
      load()
    } catch {
      toast.error('Failed to revoke access')
    } finally {
      setRevoking(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Insight Access</h1>
        <Button onClick={openGrant}>Grant Access</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {items.length} user{items.length !== 1 ? 's' : ''} with access
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12 text-muted-foreground">Loading...</div>
          ) : items.length === 0 ? (
            <div className="flex justify-center py-12 text-muted-foreground">
              No users have Insight access yet.
            </div>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden md:block overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>User</TableHead>
                      <TableHead>Language</TableHead>
                      <TableHead>Granted By</TableHead>
                      <TableHead>Granted At</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((row) => {
                      const label = displayUser(row)
                      const isEditing = editingId === row.user_id
                      return (
                        <TableRow key={row.user_id}>
                          <TableCell>
                            <p className="text-sm font-medium">{label}</p>
                            {row.username && row.first_name && (
                              <p className="text-xs text-muted-foreground">{row.first_name}</p>
                            )}
                            <p className="text-xs text-muted-foreground font-mono">{row.user_id}</p>
                          </TableCell>
                          <TableCell>
                            {isEditing ? (
                              <Select value={editLang} onValueChange={setEditLang}>
                                <SelectTrigger className="w-32">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {LANG_OPTIONS.map((o) => (
                                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : (
                              <span className="text-sm">{langLabel(row.lang)}</span>
                            )}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {displayGrantedBy(row)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDate(row.granted_at)}
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1 justify-end">
                              {isEditing ? (
                                <>
                                  <Button size="sm" disabled={inlineSaving} onClick={() => saveInline(row.user_id)}>
                                    {inlineSaving ? 'Saving...' : 'Save'}
                                  </Button>
                                  <Button size="sm" variant="ghost" onClick={cancelEdit}>Cancel</Button>
                                </>
                              ) : (
                                <>
                                  <Button size="sm" variant="ghost" onClick={() => startEdit(row)}>Edit</Button>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="text-destructive hover:text-destructive"
                                    disabled={revoking === row.user_id}
                                    onClick={() => revoke(row.user_id, label)}
                                  >
                                    {revoking === row.user_id ? 'Revoking...' : 'Revoke'}
                                  </Button>
                                </>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden divide-y divide-border">
                {items.map((row) => {
                  const label = displayUser(row)
                  return (
                    <div
                      key={row.user_id}
                      className="px-4 py-3 space-y-2 cursor-pointer active:bg-muted/50"
                      onClick={() => openSheet(row)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{label}</p>
                          <p className="text-xs text-muted-foreground font-mono">
                            {row.user_id}
                            {row.username && row.first_name && ` · ${row.first_name}`}
                          </p>
                        </div>
                        <span className="shrink-0 text-xs bg-muted text-muted-foreground rounded px-2 py-0.5">
                          {langLabel(row.lang)}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Granted by {displayGrantedBy(row)} · {formatDate(row.granted_at)}
                      </p>
                    </div>
                  )
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Mobile detail sheet */}
      <Sheet open={!!sheet} onOpenChange={(open) => !open && setSheet(null)}>
        <SheetContent side="bottom" className="rounded-t-xl space-y-4 pb-8">
          {sheet && (
            <>
              <SheetHeader>
                <SheetTitle>{displayUser(sheet)}</SheetTitle>
                <p className="text-xs text-muted-foreground font-mono">{sheet.user_id}</p>
              </SheetHeader>

              <div className="space-y-1.5">
                <Label>Response Language</Label>
                <Select value={sheetLang} onValueChange={setSheetLang}>
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

              <p className="text-xs text-muted-foreground">
                Granted by {displayGrantedBy(sheet)} on {formatDate(sheet.granted_at)}
              </p>

              <div className="flex gap-2 pt-2">
                <Button
                  className="flex-1"
                  disabled={sheetSaving || sheetLang === sheet.lang}
                  onClick={saveSheet}
                >
                  {sheetSaving ? 'Saving...' : 'Save'}
                </Button>
                <Button
                  variant="outline"
                  className="flex-1 text-destructive border-destructive/30"
                  disabled={revoking === sheet.user_id}
                  onClick={() => revoke(sheet.user_id, displayUser(sheet), true)}
                >
                  {revoking === sheet.user_id ? 'Revoking...' : 'Revoke'}
                </Button>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* Grant dialog */}
      <Dialog open={grantOpen} onOpenChange={(open: boolean) => !open && setGrantOpen(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Grant Insight Access</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="grant-query">User (@username or ID)</Label>
              <div className="relative">
                <Input
                  id="grant-query"
                  placeholder="@Adams_me or 123456789"
                  value={query}
                  onChange={(e) => { setQuery(e.target.value); setSelectedUser(null) }}
                  autoComplete="off"
                />
                {suggestions.length > 0 && (
                  <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-md">
                    {suggestions.map((u) => (
                      <button
                        key={u.id}
                        type="button"
                        className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-accent text-left"
                        onClick={() => selectSuggestion(u)}
                      >
                        <span className="font-medium">
                          {u.username ? `@${u.username}` : u.first_name ?? String(u.id)}
                        </span>
                        {u.username && u.first_name && (
                          <span className="text-muted-foreground">{u.first_name}</span>
                        )}
                        <span className="ml-auto font-mono text-xs text-muted-foreground">{u.id}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {selectedUser && (
                <p className="text-xs text-muted-foreground">
                  Selected: {selectedUser.username ? `@${selectedUser.username}` : selectedUser.first_name} (ID: {selectedUser.id})
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>Language</Label>
              <Select value={grantLang} onValueChange={setGrantLang}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {LANG_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGrantOpen(false)}>Cancel</Button>
            <Button onClick={submitGrant} disabled={granting || !selectedUser}>
              {granting ? 'Granting...' : 'Grant'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
