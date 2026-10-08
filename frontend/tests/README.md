# Credential presence tests

Run from the plugin root in the Yoink checkout:

```sh
node --test frontend/tests/credentials.test.mjs
```

The tests require Node's TypeScript stripping API. They exercise the typed API
with a recording transport and check editor wiring. They make no backend or
provider requests. Paired credential translations live in the parent frontend's
`src/locales/en.json` and `src/locales/ru.json`.

Run `just verify-fe` from the parent repository for the integrated TypeScript
check. Browser interactions and native responses require the process fixture.
