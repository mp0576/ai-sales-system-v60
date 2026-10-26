# Dashboard UI

The dashboard shell is served by `app.dashboard.api`. Static companion assets live beside this file and should be copied to the `dashboard/` directory in a web deployment.

## Security
- Configure `DASHBOARD_API_TOKEN` before loading protected data.
- Never commit a real token to source control.
- Demo API data is in-memory and is not durable.
- Production must use authenticated user identity and organization membership checks; do not trust a caller-supplied organization ID alone.
