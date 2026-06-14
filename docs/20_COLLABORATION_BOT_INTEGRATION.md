# Slack and Microsoft Teams Bot Integration

This guide explains how to configure and test the Rudix collaboration bot
interface for Slack and Microsoft Teams.

The bot endpoints are transport adapters. They normalize Slack or Teams events,
then call the same Rudix chat path used by the web app. Organization boundaries,
user mapping, source scope, document permissions, citation validation, audit
logging, and rate limits are enforced in Rudix backend services.

## Capabilities

- Slack OAuth installation flow.
- Manual Slack or Teams installation registration.
- Encrypted platform bot token storage and rotation.
- Slack slash command and app mention handling.
- Teams Activity-style message handling.
- Fast platform acknowledgement with asynchronous final response delivery.
- User mapping from Slack/Teams user IDs to Rudix users.
- Default workspace source scope plus inline `--collection` and `--document`
  selectors.
- Citation-safe links back to Rudix document routes.
- Audit logs and rate limits per provider workspace/team and external user.

## Required Environment

Set these values in `.env` before local testing:

```bash
FEATURE_ENABLE_COLLABORATION_BOTS=true
BOT_PROCESS_EVENTS_ASYNC=true
BOT_DELIVERY_TIMEOUT_SECONDS=5
RATE_LIMIT_BOT_REQUESTS=30
```

For Slack:

```bash
BOT_SLACK_SIGNING_SECRET=replace-with-slack-signing-secret
BOT_SLACK_CLIENT_ID=replace-with-slack-client-id
BOT_SLACK_CLIENT_SECRET=replace-with-slack-client-secret
BOT_SLACK_OAUTH_REDIRECT_URI=https://your-ngrok-domain.ngrok-free.dev/api/v1/bots/slack/oauth/callback
BOT_SLACK_OAUTH_SCOPES=app_mentions:read,chat:write,commands,users:read,users:read.email
```

For Teams local/custom transport validation:

```bash
BOT_TEAMS_SHARED_SECRET=replace-with-shared-local-secret
```

For local Slack testing, `API_BASE_URL` should match your public tunnel base URL
and `FRONTEND_BASE_URL` should point to the frontend users will open for
citations:

```bash
API_BASE_URL=https://your-ngrok-domain.ngrok-free.dev
FRONTEND_BASE_URL=http://localhost:3000
```

Run migrations after pulling the bot changes:

```bash
cd backend
make migrate
```

## Slack App Setup

In Slack App configuration:

1. Open `Basic Information`.
2. Copy `Signing Secret` into `BOT_SLACK_SIGNING_SECRET`.
3. Copy `Client ID` into `BOT_SLACK_CLIENT_ID`.
4. Copy `Client Secret` into `BOT_SLACK_CLIENT_SECRET`.
5. Open `OAuth & Permissions`.
6. Add redirect URL:
   `https://your-ngrok-domain.ngrok-free.dev/api/v1/bots/slack/oauth/callback`
7. Add bot scopes:
   `app_mentions:read`, `chat:write`, `commands`, `users:read`,
   `users:read.email`.
8. Open `Event Subscriptions`.
9. Enable events and set Request URL:
   `https://your-ngrok-domain.ngrok-free.dev/api/v1/bots/slack/events`
10. Subscribe to bot event: `app_mention`.
11. Optional: open `Slash Commands` and create `/rudix` with Request URL:
    `https://your-ngrok-domain.ngrok-free.dev/api/v1/bots/slack/events`
12. Reinstall the app after changing scopes or event subscriptions.

Slack URL verification is handled by the `/api/v1/bots/slack/events` endpoint.

## Slack OAuth Installation

Use an authenticated Rudix owner/admin token and active organization context.

Start OAuth:

```bash
curl -X POST "http://localhost:8000/api/v1/admin/bots/slack/oauth/start" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Open the returned `authorization_url` in a browser. After Slack redirects to
`/api/v1/bots/slack/oauth/callback`, Rudix creates or updates the Slack
installation and stores the Slack bot token encrypted.

List installations:

```bash
curl "http://localhost:8000/api/v1/admin/bots/installations" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID"
```

The response includes credential metadata only:

```json
{
  "credential": {
    "configured": true,
    "fingerprint": "sha256-hmac-fingerprint",
    "scopes": ["app_mentions:read", "chat:write", "commands"]
  }
}
```

Raw platform tokens are never returned by the API.

## Manual Installation

Manual installation is useful for Teams, local tests, or Slack workspaces where
OAuth is not used.

Create or update an installation:

```bash
curl -X POST "http://localhost:8000/api/v1/admin/bots/installations" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "slack",
    "external_workspace_id": "T123456",
    "display_name": "Rudix Slack",
    "status": "enabled",
    "default_source_scope": {"mode": "all"},
    "config": {"managed_by": "manual"}
  }'
```

Do not put tokens, secrets, passwords, credentials, or authorization headers in
`config`. The API rejects secret-like config keys.

Store or rotate the platform bot token through the credential endpoint:

```bash
curl -X PUT "http://localhost:8000/api/v1/admin/bots/installations/$INSTALLATION_ID/credential" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "bot_token": "replace-with-platform-bot-token",
    "scopes": ["chat:write"]
  }'
```

Clear a credential:

```bash
curl -X DELETE "http://localhost:8000/api/v1/admin/bots/installations/$INSTALLATION_ID/credential" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID"
```

Disable bot access for a workspace:

```bash
curl -X PATCH "http://localhost:8000/api/v1/admin/bots/installations/$INSTALLATION_ID" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"status": "disabled"}'
```

## User Mapping

Every external Slack or Teams user must be mapped to an active Rudix user in the
same organization before asking questions through the bot.

Map a user:

```bash
curl -X PUT "http://localhost:8000/api/v1/admin/bots/installations/$INSTALLATION_ID/mappings" \
  -H "Authorization: Bearer $RUDIX_ADMIN_TOKEN" \
  -H "X-Organization-ID: $RUDIX_ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "external_user_id": "U123456",
    "rudix_user_id": "00000000-0000-0000-0000-000000000000",
    "external_email": "user@example.com",
    "status": "active"
  }'
```

For Slack, use the Slack member ID such as `U123456`.

For Teams, use the Entra ID/AAD object ID when available. The Teams adapter
falls back to `from.id` if `from.aadObjectId` is not present.

## Asking Questions

Slack app mention:

```text
@Rudix What is our travel reimbursement policy?
```

Slack slash command:

```text
/rudix What is our travel reimbursement policy?
```

Source selectors:

```text
/rudix --collection 00000000-0000-0000-0000-000000000000 What is the leave policy?
/rudix --document 00000000-0000-0000-0000-000000000000 Summarize this document.
```

If no inline selector is provided, Rudix uses the installation
`default_source_scope`. If that is not set, Rudix uses normal workspace scope.

## Local Slack Test With Ngrok

1. Start the backend and frontend.
2. Start a tunnel:

```bash
ngrok http 8000
```

3. Set `API_BASE_URL` and `BOT_SLACK_OAUTH_REDIRECT_URI` to the ngrok HTTPS
   domain.
4. Restart the backend so settings reload.
5. Configure Slack Event Subscriptions and slash command URLs to the ngrok
   endpoints.
6. Run Slack OAuth start and open the returned URL.
7. Map your Slack user ID to your Rudix user.
8. Invite the bot to a test channel.
9. Mention the bot or run `/rudix`.

For direct curl testing without Slack delivery, set `X-Rudix-Bot-Sync: true`:

```bash
curl -X POST "http://localhost:8000/api/v1/bots/slack/events" \
  -H "Content-Type: application/json" \
  -H "X-Rudix-Bot-Sync: true" \
  -d '{
    "type": "event_callback",
    "team_id": "T123456",
    "event": {
      "type": "app_mention",
      "user": "U123456",
      "channel": "C123456",
      "text": "What is our leave policy?",
      "ts": "1710000000.0001"
    }
  }'
```

## Microsoft Teams Setup

The built-in Teams endpoint accepts Activity-style JSON at:

```text
POST /api/v1/bots/teams/events
```

For local/custom adapter testing, send:

```http
Authorization: Bearer <BOT_TEAMS_SHARED_SECRET>
```

Expected identity fields:

- `channelData.tenant.id` for tenant/workspace resolution.
- `channelData.team.id` for team resolution.
- `from.aadObjectId` for external user mapping when available.
- `conversation.id`, `serviceUrl`, and activity `id` for response delivery.

Minimal local payload:

```bash
curl -X POST "http://localhost:8000/api/v1/bots/teams/events" \
  -H "Authorization: Bearer $BOT_TEAMS_SHARED_SECRET" \
  -H "Content-Type: application/json" \
  -H "X-Rudix-Bot-Sync: true" \
  -d '{
    "type": "message",
    "id": "activity-id",
    "serviceUrl": "https://smba.trafficmanager.example/",
    "text": "What is the travel policy?",
    "channelData": {
      "tenant": {"id": "tenant-id"},
      "team": {"id": "team-id"}
    },
    "conversation": {"id": "conversation-id"},
    "from": {"aadObjectId": "aad-object-id"}
  }'
```

For production Teams deployments, keep Microsoft Bot Framework SDK validation in
the transport layer, then forward normalized Activity events into Rudix without
bypassing Rudix authorization, source scope, citation, audit, or rate-limit
checks.

## Response Delivery

By default, bot events acknowledge quickly and process the answer after the HTTP
response:

- Slack slash commands use `response_url`.
- Slack app mentions use `chat.postMessage` with the encrypted Slack bot token.
- Teams activities use the conversation reply endpoint with the configured
  encrypted Teams delivery token.

Use `BOT_PROCESS_EVENTS_ASYNC=false` only for local debugging. Production
platforms should use async acknowledgements to avoid Slack or Teams request
timeouts.

## Security Behavior

- Slack request signatures are verified when `BOT_SLACK_SIGNING_SECRET` is set.
- Teams local/custom requests require `BOT_TEAMS_SHARED_SECRET` when set.
- Installations are scoped by organization and provider workspace/team/tenant.
- External users must be mapped to active Rudix users.
- Disabled installations reject before retrieval.
- Source scopes use the same collection/source/document access policies as web
  chat.
- Citations are generated only from validated Rudix citations and rendered as
  Rudix document links.
- Raw questions, answers, document text, tokens, and secrets are excluded from
  bot audit metadata.
- Bot credentials are encrypted at rest and never returned by API responses.

## Troubleshooting

`This Slack or Teams workspace is not connected to Rudix.`

The incoming `team_id`, tenant ID, or team ID does not match a bot installation.
Run the Slack OAuth flow or create a manual installation for that external
workspace/team.

`Your Slack or Teams account is not mapped to a Rudix user.`

Create a mapping for the external user ID and Rudix user ID.

Slack Request URL verification fails.

Confirm the URL is:
`https://your-ngrok-domain.ngrok-free.dev/api/v1/bots/slack/events`, the backend
is running, and `BOT_SLACK_SIGNING_SECRET` matches the Slack app.

Slack slash command shows only the loading message.

Check backend logs and audit events for `bots.delivery.failed`. For slash
commands, Rudix posts the final answer to Slack `response_url`.

Slack app mention does not get a threaded answer.

Confirm the installation has an encrypted Slack bot token with `chat:write`, the
bot is in the channel, and `BOT_PROCESS_EVENTS_ASYNC=true`.

Citations open the wrong host.

Set `FRONTEND_BASE_URL` to the public frontend URL users should open.

Rate limit errors appear too quickly.

Adjust `RATE_LIMIT_BOT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`. Limits are per
provider workspace/team and external user.
