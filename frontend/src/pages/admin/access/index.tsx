import { useEffect, useState } from 'react'

import { apiClient } from '@core/lib/api-client'
import { formatDate } from '@core/lib/utils'
import type { InsightAccess } from '@insight/types'
import { Button } from '@core/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@core/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@core/components/ui/dialog'
import { Input } from '@core/components/ui/input'
import { Label } from '@core/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@core/components/ui/select'
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

export default function InsightAccessPage() {
  const [items, setItems] = useState<InsightAccess[]>([])
  const [loading, setLoading] = useState(true)

  const [grantOpen, setGrantOpen] = useState(false)
  const [grantUserId, setGrantUserId] = useState('')
  const [grantLang, setGrantLang] = useState('en')
  const [granting, setGranting] = useState(false)

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

  const openGrant = () => {
    setGrantUserId('')
    setGrantLang('en')
    setGrantOpen(true)
  }

  const submitGrant = async () => {
    const uid = parseInt(grantUserId, 10)
    if (isNaN(uid)) {
      toast.error('Invalid user ID')
      return
    }
    setGranting(true)
    try {
      await apiClient.post(`/insight/access/${uid}`, { lang: grantLang })
      toast.success(`Access granted to user ${uid}`)
      setGrantOpen(false)
      load()
    } catch {
      toast.error('Failed to grant access')
    } finally {
      setGranting(false)
    }
  }

  const revoke = async (userId: number) => {
    setRevoking(userId)
    try {
      await apiClient.delete(`/insight/access/${userId}`)
      toast.success(`Access revoked for user ${userId}`)
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
          <CardTitle>{items.length} user{items.length !== 1 ? 's' : ''} with access</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12 text-muted-foreground">Loading...</div>
          ) : items.length === 0 ? (
            <div className="flex justify-center py-12 text-muted-foreground">
              No users have Insight access yet.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User ID</TableHead>
                    <TableHead>Language</TableHead>
                    <TableHead>Granted By</TableHead>
                    <TableHead>Granted At</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((row) => (
                    <TableRow key={row.user_id}>
                      <TableCell className="font-mono text-sm">{row.user_id}</TableCell>
                      <TableCell>{row.lang}</TableCell>
                      <TableCell className="font-mono text-sm">{row.granted_by}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(row.granted_at)}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          disabled={revoking === row.user_id}
                          onClick={() => revoke(row.user_id)}
                        >
                          {revoking === row.user_id ? 'Revoking...' : 'Revoke'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={grantOpen} onOpenChange={(open: boolean) => !open && setGrantOpen(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Grant Insight Access</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="grant-uid">User ID</Label>
              <Input
                id="grant-uid"
                placeholder="123456789"
                value={grantUserId}
                onChange={(e) => setGrantUserId(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Language</Label>
              <Select value={grantLang} onValueChange={setGrantLang}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANG_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGrantOpen(false)}>
              Cancel
            </Button>
            <Button onClick={submitGrant} disabled={granting}>
              {granting ? 'Granting...' : 'Grant'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
