# Deploying Box-Box on a Raspberry Pi (self-hosted, live-timing-capable)

Box-Box's live feed (SignalR WebSocket) **cannot run on Streamlit Community Cloud** — Cloud blocks the outbound WebSocket. This runbook hosts the whole app on a Pi with open egress and exposes it publicly through a Cloudflare Tunnel. It's the reproducible version of the `boxbox.playastrova.com` deploy; use it to stand up a dedicated F1 Pi later (see `../FUTURE.md`).

Current deploy: **Raspberry Pi 4 (8GB), Debian 13 trixie, aarch64, Python 3.13**, co-located with the astrova game (capped so the game always wins). Assumes an existing Cloudflare Tunnel; adapt hostnames.

## 1. App user + code
```bash
useradd --system --create-home --home-dir /home/f1dash --shell /usr/sbin/nologin f1dash
git clone https://github.com/capy-arbs/f1-data.git /opt/f1-dashboard
chown -R f1dash:f1dash /opt/f1-dashboard
runuser -u f1dash -- git config --global --add safe.directory /opt/f1-dashboard
```

## 2. Virtualenv + deps
All runtime deps ship as prebuilt aarch64/cp313 wheels (verified 2026-07-08), so `--only-binary=:all:` installs with no source builds:
```bash
runuser -u f1dash -- python3 -m venv /opt/f1-dashboard/.venv
runuser -u f1dash -- /opt/f1-dashboard/.venv/bin/pip install -r /opt/f1-dashboard/requirements.txt --only-binary=:all:
```
`f1_data.db` is committed in the repo, so historical data works immediately — no Load Data run needed.

## 3. App service (always-on, resource-capped)
```bash
cp /opt/f1-dashboard/deploy/f1-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now f1-dashboard.service
```
The unit binds `0.0.0.0:8501`, caps CPU at 2 cores (`CPUQuota=200%`) and RAM at 1.5GB (`MemoryMax=1500M`), and uses a disk-backed FastF1 cache. Smoke test:
```bash
curl -sI http://localhost:8501            # expect HTTP/1.1 200 OK
systemctl show f1-dashboard -p CPUQuotaPerSecUSec -p MemoryMax   # caps applied
```

## 4. Auto-update (replaces Cloud push-to-deploy)
```bash
cp /opt/f1-dashboard/deploy/f1-dashboard-update.service /etc/systemd/system/
cp /opt/f1-dashboard/deploy/f1-dashboard-update.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now f1-dashboard-update.timer
```
The update service restarts the app unit, which needs privilege. Grant f1dash exactly that one command (nothing else):
```bash
echo 'f1dash ALL=(root) NOPASSWD: /usr/bin/systemctl restart f1-dashboard.service' \
  > /etc/sudoers.d/f1dash-restart
chmod 440 /etc/sudoers.d/f1dash-restart
visudo -c    # validate
```
The timer runs every 30 min: `git pull --ff-only`, and only if HEAD moved does it reinstall deps and restart. Picks up the Mon/Wed `f1_data.db` refresh commits and any code pushes.

## 5. Public URL via Cloudflare Tunnel
Add an ingress rule to the existing tunnel's config (game rule untouched), then route DNS and restart:
```yaml
# /home/astrova/.cloudflared/config.yml
ingress:
  - hostname: mp.playastrova.com        # game (existing)
    service: http://localhost:8080
  - hostname: boxbox.playastrova.com    # dashboard (new)
    service: http://localhost:8501
  - service: http_status:404
```
```bash
sudo -u astrova cloudflared tunnel route dns astrova-mp boxbox.playastrova.com
systemctl restart astrova-tunnel        # ~5s tunnel blip — do it when nobody's playing
```
(A dedicated Pi with its own tunnel: `cloudflared tunnel create`, `cloudflared tunnel route dns`, and a standalone `config.yml` + service — same shape, no co-tenant.)

## 6. Live acceptance test (PASSED 2026-07-19, Belgian GP race)
During a live session, open the **Live Session** page and confirm the diagnostic reads:
```
Recorder — thread alive: True · ws connected: True · file: <growing> bytes
```
`ws connected: True` with a growing file is the whole point — it's what Cloud could never do. If it reads `ws connected: False`, the host is blocking egress (the Cloud failure mode).

Passed on this Pi during the 2026-07-19 Belgian GP race: the recorder streamed the full race (~4.6MB, all 22 drivers) with Time-to-Strike running clean against the live data. One caveat found: a half-dead websocket (`ws connected: True` but file frozen) stalls the feed until the thread dies and revives (~9 min observed) — see project_notes.md → Known Issues (stall watchdog).

## Notes
- No F1TV token needed — the free-token SignalR path (`lambda: ""` in `data/f1_signalr.py`) is unchanged.
- Logs: `journalctl -u f1-dashboard -f` (app), `journalctl -u f1-dashboard-update -f` (updater).
- The GitHub refresh action (`.github/workflows/refresh-data.yml`) keeps committing `f1_data.db` to `main`; the Pi's timer pulls it. No change to the action.
