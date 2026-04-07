# IBKR Gateway on the Bot Box

This stack runs the IBKR paper gateway locally on `openclaw-bot` so `traderd` no longer depends on the desktop machine at `192.168.0.18`.

## Files

- `compose.yaml`: Docker Compose stack for a restartable IB Gateway container.
- `ib-gateway-paper.env.example`: template for the bot-box secret env file.
- Host secret file expected at `/home/gabernardi/.config/ib-gateway-paper.env`.
- Persistent Gateway settings stored outside the repo at `/home/gabernardi/.local/share/ib-gateway-paper/tws_settings`.

## Why this fixes the desktop dependency

`traderd` currently points at `192.168.0.18:4002`, which is the desktop-hosted IBKR Gateway API port. This stack moves the API endpoint onto the bot box itself and binds it to `127.0.0.1:4002`.

## One-time setup

1. SSH to the bot box.
2. Create the real secret file:
   - `mkdir -p /home/gabernardi/.config`
   - `cp /home/gabernardi/trader/ops/ib_gateway/ib-gateway-paper.env.example /home/gabernardi/.config/ib-gateway-paper.env`
   - edit `/home/gabernardi/.config/ib-gateway-paper.env`
   - `chmod 600 /home/gabernardi/.config/ib-gateway-paper.env`
3. Create the persistent settings directory:
   - `mkdir -p /home/gabernardi/.local/share/ib-gateway-paper/tws_settings`
4. Start the container:
   - `cd /home/gabernardi/trader/ops/ib_gateway`
   - `docker compose pull`
   - `docker compose up -d`
5. Confirm the API port is listening:
   - `ss -ltn | grep 4002`

Because the container uses `restart: unless-stopped`, Docker will bring it back after reboot once the container has been created successfully.

## Optional VNC access

If `VNC_SERVER_PASSWORD` is set in the env file, the container exposes VNC on `127.0.0.1:5900`.

Tunnel it from your laptop if you need to inspect the UI:

```bash
ssh -L 5900:127.0.0.1:5900 openclaw-bot
```

Then connect a VNC client to `localhost:5900`.

## traderd cutover

Do not change `traderd` until the local gateway is up and logged in.

After the container is healthy:

1. Change [service.yaml](/home/gabernardi/trader/config/service.yaml) `ibkr.host` from `192.168.0.18` to `127.0.0.1`.
2. Restart `traderd`.
3. Verify:
   - `curl -s http://127.0.0.1:8080/mode`
   - `curl -s http://127.0.0.1:8080/status`
   - `curl -s http://127.0.0.1:8080/strategy/mes_rsi_trend_pullback/status`

## Important limitations

- IBKR still requires Gateway or TWS as the session host. This removes the desktop dependency, not the Gateway dependency.
- If IBKR demands a fresh 2FA approval, you will still need to approve it.
- The current `traderd` process is not systemd-managed on the bot box. This stack only addresses the IB Gateway side.
