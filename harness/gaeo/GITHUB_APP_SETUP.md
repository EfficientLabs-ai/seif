# GitHub App setup (founder browser step — ~3 min)

Gives Codex/Gemini real GitHub identities (bot, short-lived installation tokens, least secret-surface). Creation is a web action; the **private key stays in the vault, never in agent context**.

## 1. Create the app
Go to **https://github.com/organizations/EfficientLabs-ai/settings/apps/new** and set:
- **GitHub App name:** `seif-bot`
- **Homepage URL:** `https://github.com/EfficientLabs-ai/seif`
- **Webhook → Active:** **uncheck** (none needed for v0.1)
- **Repository permissions:**
  - Contents: **Read and write**
  - Pull requests: **Read and write**
  - Issues: **Read and write**
  - Checks: **Read and write**
  - Metadata: Read-only (auto)
- **Where can this be installed:** Only on this account
- Click **Create GitHub App**.

## 2. Capture the App ID (NOT a secret)
Shown at the top of the app's settings page → note it.

## 3. Generate + vault the private key (SECRET — hidden)
On the app page → **Generate a private key** (downloads a `.pem` once). Then, in your prompt:
```
! umask 177; mkdir -p ~/.config/seif; mv ~/Downloads/seif-bot.*.private-key.pem ~/.config/seif/seif-bot.pem && chmod 600 ~/.config/seif/seif-bot.pem && echo "key vaulted (not shown)"
```
The key lands at `~/.config/seif/seif-bot.pem` (mode 600). It is never printed.

## 4. Install the app + get the Installation ID (NOT a secret)
App page → **Install App** → install on `EfficientLabs-ai` → select **seif** (add more repos later). After install, the URL ends in `/installations/<INSTALLATION_ID>` — note it (or I can fetch it via the API once the key is in place).

## 5. Send back (these are IDs, not secrets)
- App ID
- Installation ID (or let me fetch it)

Then I wire a token-minter (`harness/gaeo/mint_token.py`) that reads `~/.config/seif/seif-bot.pem` at runtime to mint **short-lived installation tokens** for CI/agents — the key never leaves the vault, never enters any agent's context. PAT fallback only if the App route fails.
