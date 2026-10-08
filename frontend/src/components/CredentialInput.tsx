import { useTranslation } from 'react-i18next'
import { Button, Input } from '@ui'
import { editCredential, KEEP_CREDENTIAL, type CredentialEdit } from '@insight/api/credentials'

interface Props {
  id?: string
  value: CredentialEdit
  stored: boolean
  disabled?: boolean
  onChange: (next: CredentialEdit) => void
}

export default function CredentialInput({ id, value, stored, disabled, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <div className="space-y-1.5">
      <Input
        id={id}
        type="password"
        autoComplete="new-password"
        disabled={disabled || value.kind === 'clear'}
        value={value.kind === 'replace' ? value.value : ''}
        onChange={(event) => onChange(editCredential(event.target.value))}
        placeholder={t(stored ? 'insight.credential.replace_placeholder' : 'insight.credential.new_placeholder')}
        className="font-mono text-xs"
      />
      <div className="flex items-center gap-2 text-xs">
        <span className={value.kind === 'clear' ? 'text-destructive' : 'text-muted-foreground'}>
          {t(value.kind === 'clear' ? 'insight.credential.will_clear' : stored ? 'insight.credential.stored' : 'insight.credential.not_set')}
        </span>
        {value.kind !== 'clear' && stored && (
          <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange({ kind: 'clear' })}>
            {t('insight.credential.clear')}
          </Button>
        )}
        {value.kind !== 'unchanged' && (
          <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(KEEP_CREDENTIAL)}>
            {t('insight.credential.undo')}
          </Button>
        )}
      </div>
    </div>
  )
}
