# Traderd Desktop Access

This proxy exposes the local traderd operator dashboard to Tailscale-connected devices without exposing traderd itself on the LAN.

Defaults:
- Bind host: `tailscale ip -4`
- Port: `18080`
- Upstream: `http://127.0.0.1:8080`
- Auth: HTTP Basic Auth using values from `/home/gabernardi/.config/traderd-dashboard-proxy.env`

Desktop usage:
1. Make sure the desktop is connected to the same Tailscale tailnet.
2. Open `http://<tailscale-ip>:18080`
3. Enter the configured proxy username and password.

The proxy is intended to be started by user cron at reboot and can also be launched manually:

```bash
set -a
. /home/gabernardi/.config/traderd-dashboard-proxy.env
set +a
nohup /home/gabernardi/trader/.venv/bin/python /home/gabernardi/trader/scripts/dashboard_proxy.py >> /home/gabernardi/trader/var/logs/dashboard_proxy.log 2>&1 < /dev/null &
```
