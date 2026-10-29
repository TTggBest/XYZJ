# Authorization Gate

Authorization is the first execution gate after parsing the two required parameters and resolving the channel registry entry.

## Canonical identity and token

Read the channel name, nickname/aliases, URL, and channel ID from:

```text
运营/工作流运营/公用/频道注册表.json
```

Use this canonical token path:

```text
运营/_授权令牌/youtube_accounts/<channel_id>/youtube_oauth_token.json
```

Do not inspect or print access tokens, refresh tokens, or client secrets.

## What counts as authorized

A token file merely existing is insufficient. Authorization passes only when:

1. the token can be loaded and refreshed if necessary;
2. it has the read scopes needed for YouTube Data API and YouTube Analytics API;
3. `channels.list(mine=True)` returns exactly one channel;
4. the returned channel ID equals the registry channel ID;
5. the returned channel title equals the registered channel title.

Run a profile-only read using the canonical token and retain its output as authorization evidence inside the current history batch:

```bash
YOUTUBE_TOKEN_FILE="运营/_授权令牌/youtube_accounts/<channel_id>/youtube_oauth_token.json" \
YOUTUBE_ANALYTICS_OUTPUT_ROOT="<history batch>/API原始数据/授权验证" \
python3 scripts/fetch_youtube_analytics.py --profile-only --skip-analytics
```

Read the generated `channels.csv` and require an exact channel-ID match. Do not continue merely because the command exited successfully.

## Missing or invalid authorization

Start the existing verified OAuth flow:

```bash
.venv-youtube/bin/python scripts/authorize_youtube_token.py \
  --token-file "运营/_授权令牌/youtube_accounts/<channel_id>/youtube_oauth_token.json" \
  --expected-channel-id "<channel_id>" \
  --expected-channel-title "<registered_channel_title>"
```

The script prints an authorization URL and waits for the local callback. Ask the user to open the URL, sign in, select the intended YouTube channel, and approve access. This user action is required and is not an error condition.

The authorization script verifies channel ID and title before saving the token. If the selected channel is wrong, stop and ask the user to authorize again with the correct account/channel.

After successful authorization, repeat the profile-only check. Continue to material extraction and the formal API pull only after this second check passes.

## Blockers

Stop without analyzing when:

- the channel is absent or ambiguous in the registry;
- the registry has no channel ID;
- `client_secret.json` or the authorization runtime is missing;
- the user has not completed the browser authorization;
- the authorized identity does not match the requested channel;
- the required read/analytics access is denied.

Report the exact blocker and preserve any user-supplied material folder unchanged.
