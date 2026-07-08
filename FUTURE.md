# Future / Someday

Non-urgent ideas and deferred work. Immediate bugs and tasks go in issues/commits, not here.

## Hosting
- **Dedicated domain.** The dashboard currently lives at `boxbox.playastrova.com`, sharing the astrova Cloudflare zone (and the Pi) with the game. Someday move it to a dedicated F1 domain — purely branding; the tunnel routes any hostname from any zone in the account, so it's a DNS/ingress change, not a Pi change.
- **Dedicated Pi.** The dashboard shares the astrova Pi 4 under a CPU/RAM cap (fine at ~4–5 game players). When the game outgrows that headroom, stand up a dedicated F1 Pi — `deploy/pi-setup.md` makes it copy-paste (its own tunnel instead of a co-tenant ingress rule).

## Features (not started)
- **Live track map** — driver dots on the racing line via FastF1's `session.pos_data`. Phased plan in `project_notes.md`.
- **Pit-window predictor** — best lap to pit given tire age + traffic.
- **Undercut/overcut calculator.**
- **Equal-area projection** for track outlines (fix Mercator squash at high latitude).
- **Per-circuit rotation table** to match F1.com's stylized track diagrams.
- **Accurate start/finish marker** on track outlines (bacinger GeoJSON doesn't encode the line — needs a hand-curated index per circuit or FastF1 position data).
- **Team radio playback** — FastF1 doesn't expose it; would need to scrape F1's audio archive or wait for FastF1 support.
