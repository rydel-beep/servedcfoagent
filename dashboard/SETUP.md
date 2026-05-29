# Dashboard Chat Setup

The dashboard works fully without the Anthropic API key (numbers, charts, refresh all functional).
To enable the embedded chat panel:

1. Go to https://console.anthropic.com → API keys
2. Create a key labelled "served-cfo-dashboard"
3. In Railway dashboard for the CFO agent service, add env var:
   ```
   ANTHROPIC_API_KEY=sk-ant-...your-key...
   ```
4. Also add a dashboard token for production access:
   ```
   DASHBOARD_TOKEN=your-chosen-token-here
   ```
5. Redeploy the service (it'll pick up the new env vars)

## First Login

Visit: `https://web-production-16b16.up.railway.app/dashboard?t=YOUR_TOKEN`

The token is set via cookie on first visit — subsequent visits don't need the query param.
