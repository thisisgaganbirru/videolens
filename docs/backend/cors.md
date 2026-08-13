# Browser CORS configuration

The API accepts browser requests only from the comma-separated origins in
`ALLOWED_ORIGINS`. Local defaults include both `http://localhost:3000` (the
Docker Compose frontend) and `http://localhost:3005` (the `npm run dev`
frontend).

**Files**
- `backend/app/infrastructure/config.py` parses `ALLOWED_ORIGINS` through
  `Settings.allowed_origin_list`.
- `backend/app/interface/api/app.py` passes that list to FastAPI's
  `CORSMiddleware`.
- `backend/.env.example` and `docker-compose.yml` define local defaults.

When adding a deployed frontend, set `ALLOWED_ORIGINS` to its exact origin.
Multiple origins must be comma-separated. Restart the API after changing the
environment because middleware is configured when the module is imported.

The accepted request headers are `Authorization`, `Content-Type`,
`X-Client-ID`, and `X-Gemini-Api-Key`; the accepted methods are `GET`, `POST`,
and `OPTIONS`.
