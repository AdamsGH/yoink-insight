import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { credentialField, credentialQuery, credentialValue, editCredential, KEEP_CREDENTIAL } from '../src/api/credentials.ts'

// Load the real typed API with a recording transport; no server or provider calls.
const calls = []
globalThis.__insightPresenceTransport = Object.fromEntries(['get', 'post', 'put', 'patch', 'delete'].map(method => [method, (url, body) => {
  calls.push({ method, url, body })
  return Promise.resolve({ data: body })
}]))
const apiSource = readFileSync(new URL('../src/api/insight.ts', import.meta.url), 'utf8')
  .replace("import { apiClient } from '@core/lib/api-client'", 'const apiClient = globalThis.__insightPresenceTransport')
  .replace("from './credentials'", `from '${new URL('../src/api/credentials.ts', import.meta.url).href}'`)
const { insightApi } = await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(apiSource)).toString('base64')}`)
const config = { allowed_models: ['model-b'], default_model: 'model-b', gateway_base_url: 'https://gateway.invalid', ai_route_mode: 'auto' }
const adminBody = (gateway, openrouter) => ({ ...config, ...credentialField('gateway_api_key', gateway), ...credentialField('openrouter_api_key', openrouter) })

test('unrelated model/config save omits both credentials on the wire', async () => {
  await insightApi.patchTldrConfig(adminBody(KEEP_CREDENTIAL, KEEP_CREDENTIAL))
  assert.deepEqual(calls.at(-1), { method: 'patch', url: '/insight/config/tldr', body: config })
})
test('replacing one key omits the other; explicit clear is empty, not a sentinel', async () => {
  await insightApi.patchTldrConfig(adminBody(editCredential('replacement'), KEEP_CREDENTIAL))
  assert.deepEqual(calls.at(-1).body, { ...config, gateway_api_key: 'replacement' })
  await insightApi.patchTldrConfig(adminBody(KEEP_CREDENTIAL, { kind: 'clear' }))
  assert.deepEqual(calls.at(-1).body, { ...config, openrouter_api_key: '' })
})
test('save-reset and undo keep the next unrelated save credential-free', async () => {
  let draft = editCredential('replacement')
  await insightApi.patchTldrConfig(adminBody(draft, KEEP_CREDENTIAL))
  draft = KEEP_CREDENTIAL
  await insightApi.patchTldrConfig(adminBody(draft, KEEP_CREDENTIAL))
  assert.deepEqual(calls.at(-1).body, config)
  assert.deepEqual(editCredential(''), KEEP_CREDENTIAL)
  assert.equal(credentialValue(KEEP_CREDENTIAL), undefined)
})
test('BYOK save/test distinguish stored omission, replacement, and explicit empty', async () => {
  for (const edit of [KEEP_CREDENTIAL, editCredential('new-key'), { kind: 'clear' }]) {
    const body = { provider: 'openai', base_url: null, ...credentialField('api_key', edit) }
    await insightApi.testByok(body)
    assert.deepEqual(calls.at(-1).body, body)
    assert.equal(Object.hasOwn(calls.at(-1).body, 'api_key'), edit.kind !== 'unchanged')
    await insightApi.saveByok({ ...body, model: 'model-b' })
    assert.deepEqual(calls.at(-1).body, { ...body, model: 'model-b' })
    if (edit.kind === 'clear') assert.equal(calls.at(-1).body.api_key, '')
  }
})
test('saved gateway probes/model lists omit api_key; explicit empty never becomes stored fallback', async () => {
  await insightApi.testGateway(config.gateway_base_url, credentialValue(KEEP_CREDENTIAL))
  assert.equal(new URL(calls.at(-1).url, 'https://local.invalid').searchParams.has('api_key'), false)
  await insightApi.listModels({ apiKey: credentialValue(KEEP_CREDENTIAL) })
  assert.equal(calls.at(-1).url, '/insight/models')
  for (const method of [key => insightApi.testGateway(undefined, key), key => insightApi.listModels({ apiKey: key })]) {
    await method('')
    const params = new URL(calls.at(-1).url, 'https://local.invalid').searchParams
    assert.equal(params.has('api_key'), true)
    assert.equal(params.get('api_key'), '')
    await method('new&key')
    assert.equal(new URL(calls.at(-1).url, 'https://local.invalid').searchParams.get('api_key'), 'new&key')
  }
  assert.equal(credentialQuery(), '')
})
test('editors use presence serialization and reset without copying redacted secrets', () => {
  const admin = readFileSync(new URL('../src/pages/admin/TldrConfigPage.tsx', import.meta.url), 'utf8')
  assert.match(admin, /credentialField\('gateway_api_key', gatewayKey\)/)
  assert.match(admin, /credentialField\('openrouter_api_key', openrouterKey\)/)
  assert.doesNotMatch(admin, /set(?:Gateway|Openrouter)Key\([^)]*\.data\./)
  assert.doesNotMatch(admin, /apiKey: cfgRes\.data\./)
  const byok = readFileSync(new URL('../src/pages/settings/ByokCard.tsx', import.meta.url), 'utf8')
  assert.equal((byok.match(/credentialField\('api_key', apiKey\)/g) ?? []).length, 3)
  assert.doesNotMatch(byok, /api_key_masked|__clear__|api_key:.*null/)
  assert.match(byok, /setApiKey\(KEEP_CREDENTIAL\)/)
})
test('clear/undo UI is explicit and magic-looking input remains a replacement', () => {
  assert.deepEqual(editCredential('__clear__'), { kind: 'replace', value: '__clear__' })
  const ui = readFileSync(new URL('../src/components/CredentialInput.tsx', import.meta.url), 'utf8')
  assert.match(ui, /onChange\(\{ kind: 'clear' \}\)/)
  assert.match(ui, /onChange\(KEEP_CREDENTIAL\)/)
  assert.match(ui, /value=\{value.kind === 'replace' \? value.value : ''\}/)
})
test('GitHub token edits also omit unchanged values and support key-only clear', async () => {
  for (const edit of [KEEP_CREDENTIAL, editCredential('token-replacement'), { kind: 'clear' }]) {
    const body = { lang: 'ru', ...credentialField('github_token', edit) }
    await insightApi.patchSettings(body)
    assert.deepEqual(calls.at(-1).body, body)
    assert.equal(Object.hasOwn(body, 'github_token'), edit.kind !== 'unchanged')
  }
})
test('credential locale resources have matching nonblank English/Russian keys', () => {
  const en = JSON.parse(readFileSync(new URL('../../../../frontend/src/locales/en.json', import.meta.url), 'utf8')).insight.credential
  const ru = JSON.parse(readFileSync(new URL('../../../../frontend/src/locales/ru.json', import.meta.url), 'utf8')).insight.credential
  assert.deepEqual(Object.keys(en).sort(), Object.keys(ru).sort())
  assert.equal(Object.keys(en).length, 7)
  for (const locale of [en, ru]) for (const value of Object.values(locale)) assert.ok(typeof value === 'string' && value.trim())
})
