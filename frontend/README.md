# EDM-Auditor frontend

A React interface for the EDM-Auditor API. The screens are described in the root
[`README.md`](../README.md); the decisions made while building them are kept in the archived plan
[`docs/archive/feature-frontend.md`](../docs/archive/feature-frontend.md).

## Setup

To run the whole system in Docker, see [`docs/docker.md`](../docs/docker.md). The Docker image serves the
build with nginx (`docker/nginx.conf`), which forwards `/api` to the backend.

Node.js 22.22 or newer is required. Start the backend first, as described in
[`backend/README.md`](../backend/README.md), then run from `frontend/`:

```bash
npm install
npm run dev
```

Open <http://localhost:5173>. Vite forwards `/api` and `/health` to `http://127.0.0.1:8000`; set
`EDM_API_URL` to use another address. The API has no CORS, so the browser must reach it through this
proxy. If the backend is not running, the interface reports that the server is unavailable.

| Command             | Purpose                                                 |
|---------------------|---------------------------------------------------------|
| `npm run dev`       | Development server with the API proxy                   |
| `npm run build`     | Type check and production build into `dist/`            |
| `npm test`          | Tests; they need no backend, network or model           |
| `npm run typecheck` | Type check only                                         |
| `npm run api:types` | Regenerate `src/api/schema.d.ts` from a running backend |

Run `npm run api:types` after changing the API and commit the result. It reads
`${EDM_API_URL:-http://127.0.0.1:8000}/openapi.json`.

## Rules for the code

- **API calls** go only through `src/api/client.ts`. Errors become `ApiError` with the API error code.
  Paginated lists use `apiRequestPage`, which reads `X-Total-Count`.
  Files, such as the exported report, use `apiDownload` and `saveFile` from `src/lib/download.ts`, so
  a future sign-in header reaches downloads too and errors are shown as usual.
- **Requests that call the model** (legal act upload, audit, reprocessing) are never repeated
  automatically: a repeat spends the model's request limit. They are mutations, and the user repeats
  them with the retry button.
- **Permissions.** Screens check permissions with `useAuth().can(...)` or `<Can>`, never roles. Every
  screen is declared in `src/app/routes.tsx` with a permission; the menu and the route protection come
  from that list. Without sign-in the local session has every permission.
- **Texts** come from `src/i18n/ru.ts` through `useI18n().t(...)`. Error messages are keyed by API
  error code, as `error.<code>`. Dates and numbers are formatted through `useI18n()`; API dates have no
  time zone and are read as UTC by `parseApiDate`.
- **Colors** come from CSS variables in `src/styles/index.css`, used through semantic utilities such as
  `bg-card` or `text-severity-critical`. Palette classes such as `bg-red-500` are not used, so a theme
  only redefines the variables.
- **Document text and model output** are rendered as React text, never as HTML.

## Source layout

| Path              | Contents                                                                                                   |
|-------------------|------------------------------------------------------------------------------------------------------------|
| `src/api/`        | API client, endpoints, generated schema and shared types                                                   |
| `src/app/`        | Routes, router, layout, providers, query client                                                            |
| `src/auth/`       | Permissions, session, `AuthProvider`, `<Can>`, route guard                                                 |
| `src/components/` | Shared components; `ui/` holds shadcn/ui primitives                                                        |
| `src/features/`   | Screens with their logic: `documents/`, `audit/`, `legalActs/`, `rules/`, `documentTypes/`, shared queries |
| `src/i18n/`       | Dictionary and formatting                                                                                  |
| `src/pages/`      | Generic pages: not found, forbidden, crash                                                                 |
| `src/styles/`     | Tailwind entry point and theme variables                                                                   |
| `docker/`         | nginx configuration of the Docker image                                                                    |

shadcn/ui is configured in `components.json`; add a component with `npx shadcn@latest add <name>`.
