import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, ExternalLink, GitBranch, Loader2 } from 'lucide-react'
import { toast } from '@core/components/ui/toast'

import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogActions,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@ui'

import { insightApi, type GithubDeviceFlowStatus } from '@insight/api/insight'

export function GithubWriteCard() {
  const [status, setStatus] = useState<{ enabled: boolean; configured: boolean } | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const reload = useCallback(async () => {
    try {
      const r = await insightApi.getWriteTokenStatus()
      setStatus(r.data)
    } catch { /* not critical */ }
  }, [])

  useEffect(() => { void reload() }, [reload])

  async function onRevoke() {
    try {
      await insightApi.deleteWriteToken()
      toast.success('GitHub write access revoked')
      void reload()
    } catch {
      toast.error('Failed to revoke')
    }
  }

  if (!status?.configured) return null

  return (
    <>
      <Card>
        <CardHeader className="px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <GitBranch className="h-4 w-4 shrink-0 text-primary" />
              GitHub write access
              {status.enabled && (
                <span className="text-xs font-medium text-green-500">&#x2713;</span>
              )}
            </CardTitle>
            {status.enabled ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                onClick={onRevoke}
              >
                Revoke
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2 text-xs"
                onClick={() => setDialogOpen(true)}
              >
                Connect
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-3">
          <p className="text-xs text-muted-foreground">
            Allows starring and unstarring repos from yoink. Uses a separate OAuth App with{' '}
            <code className="font-mono">public_repo</code> scope; your read-only token is not affected.
          </p>
        </CardContent>
      </Card>

      <UpgradeScopeDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSuccess={() => { setDialogOpen(false); void reload() }}
      />
    </>
  )
}


function UpgradeScopeDialog({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [flowStatus, setFlowStatus] = useState<GithubDeviceFlowStatus | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const pollTimer = useRef<number | null>(null)

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }, [])

  const schedule = useCallback((intervalSec: number, run: () => void) => {
    stopPolling()
    pollTimer.current = window.setTimeout(run, Math.max(intervalSec, 1) * 1000)
  }, [stopPolling])

  const poll = useCallback(async () => {
    try {
      const resp = await insightApi.getPublicRepoLoginStatus()
      const next = resp.data
      setFlowStatus(next)
      if (next.status === 'pending') {
        schedule(next.interval ?? 5, () => { void poll() })
        return
      }
      if (next.status === 'success') {
        toast.success(next.username
          ? `Connected as @${next.username}`
          : 'GitHub write access connected.')
        onSuccess()
        return
      }
      if (next.status === 'expired' || next.status === 'error') {
        setError(next.error || next.status)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [onSuccess, schedule])

  const start = useCallback(async () => {
    setStarting(true)
    setError(null)
    setCopied(false)
    try {
      const resp = await insightApi.startPublicRepoLogin()
      const initial = resp.data
      setFlowStatus({
        status: 'pending',
        user_code: initial.user_code,
        verification_uri: initial.verification_uri,
        expires_at: initial.expires_at,
        interval: initial.interval,
      })
      schedule(initial.interval ?? 5, () => { void poll() })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }, [poll, schedule])

  useEffect(() => {
    if (open) { void start() }
    else { stopPolling(); setFlowStatus(null); setError(null); setCopied(false) }
    return stopPolling
  }, [open, start, stopPolling])

  const copyCode = useCallback(async () => {
    if (!flowStatus?.user_code) return
    try {
      await navigator.clipboard.writeText(flowStatus.user_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Copy failed')
    }
  }, [flowStatus?.user_code])

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            Connect GitHub write access
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          {starting && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Requesting device code...
            </div>
          )}
          {!starting && flowStatus?.user_code && (
            <>
              <p className="text-sm leading-snug text-muted-foreground">
                Copy the code, open GitHub's device page, and paste it in. You'll be asked to
                authorise <code className="font-mono text-xs">public_repo</code> access.
              </p>
              <div className="relative rounded-lg bg-background px-4 py-4 ring-1 ring-inset ring-border">
                <span className="block select-all text-center font-mono text-2xl font-semibold tracking-[0.4em]">
                  {flowStatus.user_code}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="absolute right-1.5 top-1/2 h-8 w-8 -translate-y-1/2 p-0"
                  onClick={() => { void copyCode() }}
                >
                  {copied
                    ? <Check className="h-4 w-4 text-green-500" />
                    : <Copy className="h-4 w-4" />}
                </Button>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="w-full"
                onClick={() => window.open(flowStatus.verification_uri, '_blank', 'noopener,noreferrer')}
              >
                <ExternalLink className="mr-2 h-4 w-4" />
                Open github.com/login/device
              </Button>
              {flowStatus.status === 'pending' && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Waiting for authorisation on GitHub...
                </div>
              )}
            </>
          )}
          {(flowStatus?.status === 'expired' || flowStatus?.status === 'error' || error) && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error ?? flowStatus?.error ?? (flowStatus?.status === 'expired'
                ? 'Code expired, try again.'
                : 'Connection failed.')}
            </div>
          )}
        </div>
        {(flowStatus?.status === 'expired' || flowStatus?.status === 'error' || error) && (
          <DialogActions>
            <Button type="button" size="sm" onClick={() => { void start() }} disabled={starting}>
              Try again
            </Button>
          </DialogActions>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default GithubWriteCard
