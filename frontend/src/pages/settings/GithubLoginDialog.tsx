import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy, ExternalLink, KeyRound, Loader2 } from 'lucide-react'

import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@ui'
import { toast } from '@core/components/ui/toast'
import { insightApi, type GithubDeviceFlowStatus } from '@insight/api/insight'

// Mirror of gateway's CopilotReauthDialog: kicks off the GitHub device-flow,
// shows the user_code with copy + 'open verification URL' buttons, polls
// /insight/github/login/status at the GitHub-supplied interval until the
// flow ends (success / expired / error). On success, the parent re-pulls
// /insight/settings/me so `github_token_set: true` flips on without reload.

export interface GithubLoginDialogProps {
  open: boolean
  onClose: () => void
  onSuccess: (username: string | null) => void
}

export function GithubLoginDialog({ open, onClose, onSuccess }: GithubLoginDialogProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<GithubDeviceFlowStatus | null>(null)
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
      const resp = await insightApi.getGithubLoginStatus()
      const next = resp.data
      setStatus(next)
      if (next.status === 'pending') {
        schedule(next.interval ?? 5, () => { void poll() })
        return
      }
      if (next.status === 'success') {
        toast.success(
          next.username
            ? t('insight.github_login_success_user', {
                defaultValue: 'GitHub linked as @{{username}}',
                username: next.username,
              })
            : t('insight.github_login_success_generic', { defaultValue: 'GitHub linked.' }),
        )
        onSuccess(next.username ?? null)
        onClose()
        return
      }
      if (next.status === 'expired' || next.status === 'error') {
        setError(next.error || next.status)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [onClose, onSuccess, schedule, t])

  const start = useCallback(async () => {
    setStarting(true)
    setError(null)
    setCopied(false)
    try {
      const resp = await insightApi.startGithubLogin()
      const initial = resp.data
      setStatus({
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
    if (open) {
      void start()
    } else {
      stopPolling()
      setStatus(null)
      setError(null)
      setCopied(false)
    }
    return stopPolling
  }, [open, start, stopPolling])

  const copyCode = useCallback(async () => {
    if (!status?.user_code) return
    try {
      await navigator.clipboard.writeText(status.user_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error(t('common.copy_failed', { defaultValue: 'Copy failed' }))
    }
  }, [status?.user_code, t])

  const openVerification = useCallback(() => {
    if (status?.verification_uri) {
      window.open(status.verification_uri, '_blank', 'noopener,noreferrer')
    }
  }, [status?.verification_uri])

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            {t('insight.github_login_title', { defaultValue: 'Sign in with GitHub' })}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {starting && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('insight.github_login_starting', { defaultValue: 'Asking GitHub for a device code...' })}
            </div>
          )}

          {!starting && status?.user_code && (
            <>
              <p className="text-sm leading-snug text-muted-foreground">
                {t('insight.github_login_step1', {
                  defaultValue: 'Copy the code below, open the GitHub verification page, and paste it in.',
                })}
              </p>

              {/* Code panel: centered glyph block, copy button parked at the right edge so it never
                  shifts the visual centre. Background uses bg-background + ring for the inset look the
                  miniapp uses elsewhere (BYOK card, model picker) instead of the near-invisible bg-muted/40. */}
              <div className="relative rounded-lg bg-background ring-1 ring-inset ring-border px-4 py-4">
                <span
                  className="block text-center font-mono text-2xl font-semibold tracking-[0.4em] text-foreground select-all"
                  aria-label={t('insight.github_login_code_label', { defaultValue: 'Device code' })}
                >
                  {status.user_code}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 h-8 w-8 p-0"
                  onClick={() => { void copyCode() }}
                  aria-label={t('common.copy', { defaultValue: 'Copy' })}
                >
                  {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>

              <Button
                type="button"
                size="sm"
                variant="outline"
                className="w-full"
                onClick={openVerification}
              >
                <ExternalLink className="mr-2 h-4 w-4" />
                {t('insight.github_login_open_url', { defaultValue: 'Open github.com/login/device' })}
              </Button>

              {status.status === 'pending' && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t('insight.github_login_waiting', { defaultValue: 'Waiting for you to authorise on GitHub...' })}
                </div>
              )}
            </>
          )}

          {(status?.status === 'expired' || status?.status === 'error' || error) && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error
                ?? status?.error
                ?? (status?.status === 'expired'
                  ? t('insight.github_login_expired', { defaultValue: 'Code expired, start a new login.' })
                  : t('insight.github_login_error_generic', { defaultValue: 'Login failed.' }))}
            </div>
          )}
        </div>

        {/* No bottom Close button: the dialog header already carries an X.
            Retry stays visible only when the flow ended badly (expired/error). */}
        {(status?.status === 'expired' || status?.status === 'error' || error) && (
          <DialogActions>
            <Button type="button" size="sm" onClick={() => { void start() }} disabled={starting}>
              {t('insight.github_login_retry', { defaultValue: 'Try again' })}
            </Button>
          </DialogActions>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default GithubLoginDialog
