# Deploying mX to Fly.io

One container runs the API and serves the web app. The SQLite database lives on a
Fly volume mounted at `/data`. Expected cost: about **$2/month** (a shared-cpu-1x
machine with 512 MB, plus a 1 GB volume), and less when the machine auto-stops
while idle. Fly requires a card on file.

## What you need
- A Fly.io account with a card on file: sign up at https://fly.io.
- The `fly` command-line tool. Install it in PowerShell:
  ```powershell
  iwr https://fly.io/install.ps1 -useb | iex
  ```
  Then open a **new** terminal and check that it works with `fly version`.
- Your production secrets:
  - `MX_API_KEY`: a new random key. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
  - `MX_PASSWORD`: the web login password. Use a long one, at least 12 characters; a password manager helps.
  - `ANTHROPIC_API_KEY`: from console.anthropic.com. Keep its spend limit on.

## First deploy
Run these from the project root, `C:\Users\maesp\FA26\mX`.

1. **Sign in to Fly**. This opens the browser:
   ```powershell
   fly auth login
   ```
2. **Create the app from the existing `fly.toml`**, without deploying yet. When it asks, copy the existing configuration, pick an app name (for example `mx-rio`) and the region nearest you, and say **no** to databases and Redis.
   ```powershell
   fly launch --no-deploy
   ```
   Check that `fly.toml` now shows your app name, and that `primary_region` is the region you picked.
3. **Create the volume for the database** in the same region as `primary_region`:
   ```powershell
   fly volumes create mx_data --size 1 --region iad
   ```
4. **Set the secrets without typing them into the terminal**, so they don't end up in your shell history. Create a temporary file `secrets.env` **outside the repo** (for example on your Desktop):
   ```
   MX_API_KEY=...
   MX_PASSWORD=...
   ANTHROPIC_API_KEY=...
   ```
   Then import it and delete the file:
   ```powershell
   Get-Content $HOME\Desktop\secrets.env | fly secrets import
   Remove-Item $HOME\Desktop\secrets.env
   ```
5. **Deploy**. Fly builds the Docker image on its own servers, so Docker isn't needed on your laptop:
   ```powershell
   fly deploy
   ```
6. **Make sure exactly one machine runs**, because SQLite can't be shared between two:
   ```powershell
   fly scale count 1
   ```
7. **Open it** at `https://<your-app>.fly.dev` and sign in with `MX_PASSWORD`.

## Check it works
- `fly status` should show one machine in the `started` state, and the `/health` check passing.
- `fly logs` should show `Uvicorn running` and, after you chat, one `mx.chat ... status=ok` line per reply. Message text is never logged.
- Ask a hard question in Normal mode. Replies that think for more than a minute stay connected, because the server sends a heartbeat every 15 seconds.

## Everyday tasks
| Task | Command |
|---|---|
| Deploy new code (after merging on GitHub and pulling) | `fly deploy` |
| See logs | `fly logs` |
| Change a secret (the app restarts) | `fly secrets set MX_PASSWORD=...`, or `fly secrets import` as above |
| Sign out every device | Change `MX_API_KEY`, which also signs the session cookies |
| List past releases | `fly releases` |
| Open a shell in the machine | `fly ssh console` |

## Backups
Fly snapshots volumes daily and keeps them for a few days. List them with `fly volumes snapshots list <volume-id>`, where `fly volumes list` shows the id. For your own copy of the database:
```powershell
fly ssh sftp get /data/mx.db mx-backup.db
```

## Troubleshooting
- **The app keeps restarting.** Run `fly logs`. `MX_API_KEY must be...` or `MX_PASSWORD must be...` means a secret is missing or too short; fix it with `fly secrets set`.
- **"Too many wrong passwords."** Five wrong tries lock the login for 15 minutes, and the `MX_API_KEY` header still works during that time. Wait it out, or restart the app with `fly apps restart`.
- **Conversations disappeared after a deploy.** Check that `fly volumes list` shows `mx_data` attached, and that `fly scale count 1` is in effect. A second machine gets its own empty volume.
