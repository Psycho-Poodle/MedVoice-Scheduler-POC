# Cloudflare Tunnel for Vapi

Use this when you want Vapi to call the backend running on your local machine instead of the Render free backend.

Cloudflare Tunnel creates an outbound-only HTTPS path from Cloudflare to your local Docker network, so you do not need a public IP address, router port forwarding, or an upgraded Render plan.

## Recommended Setup

1. In Cloudflare Zero Trust, create a tunnel.
2. Choose Docker as the connector.
3. Copy the generated tunnel token.
4. Add it to your local `.env`:

```env
CLOUDFLARE_TUNNEL_TOKEN=your_cloudflare_tunnel_token
```

5. Add a public hostname in the tunnel settings:

```text
Hostname: api.your-domain.com
Service type: HTTP
Service URL: backend:8000
```

The `backend` hostname is the Docker Compose service name. Do not use `localhost` here because the `cloudflared` container has its own network namespace.

6. Start the local stack with the tunnel profile:

```powershell
docker compose --profile tunnel up -d --build
```

7. Check backend health through the public hostname:

```text
https://api.your-domain.com/health
```

8. In Vapi, set every tool server URL to:

```text
https://api.your-domain.com/api/v1/vapi/tool-calls
```

Keep the tools synchronous. Do not enable async mode for the booking tools.

## Quick Test

In Vapi's tool test, or with any HTTP client, test doctor search:

```http
POST https://api.your-domain.com/api/v1/vapi/tool-calls
Content-Type: application/json

{
  "message": {
    "toolCallList": [
      {
        "id": "test-1",
        "name": "search_doctors",
        "arguments": {
          "query": "cardiologist"
        }
      }
    ]
  }
}
```

Expected response shape:

```json
{
  "results": [
    {
      "toolCallId": "test-1",
      "name": "search_doctors",
      "result": "{\"doctors\": [...]}"
    }
  ]
}
```

## Temporary Testing Without a Domain

Cloudflare can create temporary `trycloudflare.com` URLs, but they are not stable. Use them only for quick manual tests, not for a Vapi assistant that needs a persistent tool URL.

For a reliable Vapi setup, use a Cloudflare-managed domain and a named tunnel.
