# mX on your phone

mX stays on the laptop, bound to `127.0.0.1`. The phone reaches it through Tailscale's private HTTPS proxy. That proxy is not the public internet.

Do not run `tailscale funnel`. Funnel would publish mX to the internet.

## Once

1. Install Tailscale on the laptop and the phone, and sign both into the same tailnet.
2. In the Tailscale admin console, turn on MagicDNS and HTTPS certificates. Check the current clicks in Tailscale's docs for the version you installed; the names of those switches have changed before.
3. On the laptop, proxy HTTPS on the laptop's `*.ts.net` name to mX:

   ```powershell
   tailscale serve --bg 8000
   ```

   That is the syntax for Tailscale's current `serve` command: it serves HTTPS and forwards to `http://127.0.0.1:8000`. Confirm with `tailscale serve --help` on your machine before relying on it.

   `tailscale serve status` should print an `https://<laptop>.<tailnet>.ts.net` URL.

## Each time

1. Start mX with `.\start-mx.ps1 -Phone`. The script checks that Tailscale is installed and that `serve` is already running, then prints the phone URL. It does not change Tailscale's config.
2. On the phone, open that `https://…ts.net` URL, sign in with `MX_PASSWORD`, and use mX as on the laptop (streaming, tools, memory cards). The laptop has to be awake with mX running.
3. The session cookie is `Secure`, which is why the phone needs HTTPS. `http://` on the LAN will not keep you signed in.

## Turn the proxy off

```powershell
tailscale serve off
```

If that flag isn't in your version, `tailscale serve reset` clears the config. Check `tailscale serve --help`. Either way, uvicorn can keep running for the laptop.

## Checklist

- [ ] The phone URL is `https://`, on your tailnet, and the page loads.
- [ ] Sign-in works and stays signed in after a refresh (the Secure cookie).
- [ ] A reply streams, including a tool step if tools are on.
- [ ] A memory card can be saved, and the Memory page lists it.
- [ ] `tailscale funnel` is not enabled (`tailscale serve status` shows no public funnel).
