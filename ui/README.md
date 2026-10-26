# Review UI

React + TypeScript + Vite front end for the local review server (`scianim serve`). It talks only to the
documented HTTP API under `/api` and never executes generated code.

```bash
npm ci              # once
npm run dev         # http://localhost:5173 with /api proxied to a running `scianim serve`
npm run build       # type-checks and writes the bundle into ../src/scianim/server/static (committed)
```

The build output is committed so that `uv run scianim serve` works without Node; CI rebuilds it and fails
if the committed bundle is stale.
