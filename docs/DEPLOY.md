# Deploying Bakar

> **Project owner:** rocksgimli@gmail.com (LiveKit Cloud account for the Bakar deployment).

Bakar is **three pieces**, and only one of them is a website:

| Piece | What it is | Where it can run |
|---|---|---|
| **Frontend** | Next.js 15 app, mint tokens, render UI | Vercel, Netlify |
| **Agent worker** | Long-lived Python process holding a WebSocket to LiveKit | Fly.io, Railway, Render, any VPS with Docker |
| **LiveKit Cloud** | Media plane, rooms, dispatch, SIP | SaaS — nothing to deploy |

**The agent cannot go on Vercel or Netlify.** It is a persistent worker, not a request handler: it registers with LiveKit and waits for jobs over a websocket. Serverless functions sleep between requests and would deregister. If only the frontend is deployed, the page loads, the token works, and the room is silent.

So the minimal public deployment is: **frontend on Vercel (or Netlify) + agent on Fly.io (or Railway) + the LiveKit project you already have.**

---

## 1. Frontend on Vercel (recommended)

1. Push `S:\Bakar` to a Git repository (GitHub/GitLab/Bitbucket).
2. vercel.com → **Add New → Project** → import the repo.
3. **Root Directory:** `frontend`.
4. Framework preset: Next.js (auto-detected). Build command and output are defaults.
5. Environment variables (Production + Preview):

   | Variable | Value |
   |---|---|
   | `LIVEKIT_URL` | `wss://gimli-bakar-rcjx7kir.livekit.cloud` |
   | `LIVEKIT_API_KEY` | your key |
   | `LIVEKIT_API_SECRET` | your secret |
   | `AGENT_NAME` | `bakar-agent` |

6. Deploy.

`vercel.json` is intentionally absent — a standard Next.js app needs no configuration there.

**Make it private first.** Project → Settings → Deployment Protection → enable *Password* (or *Vercel Authentication*). Without it, anyone with the URL can mint tokens and spend your Deepgram/LLM/Murf budget; `/api/token` has no authentication of its own (see *Security* below).

## 2. Frontend on Netlify

`netlify.toml` at the repository root already points the build at `frontend/`:

1. app.netlify.com → **Add new site → Import an existing project**.
2. Connect the repo. Build settings are read from `netlify.toml` (base `frontend`, publish `.next`, Node 22).
3. Environment variables — same four as Vercel (Site configuration → Environment variables).
4. Deploy.

Netlify installs its Next.js runtime automatically; do not add `@netlify/plugin-nextjs` to `package.json` — a pinned version goes stale faster than the auto-installed one.

## 3. Agent on LiveKit Cloud (managed — least infrastructure)

LiveKit Cloud can host the worker itself: no second vendor, no servers to patch, and the
laptop can be off. The `lk` CLI is already installed on this machine.

```bash
cd backend
lk cloud auth        # browser login to your LiveKit project
lk agent create      # register this agent as a Cloud deployment
lk agent deploy      # push updates later
```

Two things to keep straight:

- **The name you register becomes the dispatch name.** Use `bakar-agent` so it matches the
  frontend's `AGENT_NAME` (and remember to update that value on Netlify/Vercel if it changes).
- **Provider keys live in the LiveKit dashboard** for the deployment (`DEEPGRAM_API_KEY`,
  `MURF_API_KEY`, LLM credentials) — same rule as everywhere else: never in the repo.

For quick demos there is also a hosted **Sandbox URL**: a LiveKit Cloud sandbox can serve a
frontend for the agent, so you can share a working link before Netlify is even set up.

Cost, limits and scaling for managed agents are shown on the LiveKit dashboard's Agents page —
check them against your plan before sharing the link publicly.

## 4. Agent worker on Fly.io

The `Dockerfile` already downloads models at build time and starts the worker with the absolute path `/app/.venv/bin/python /app/src/agent.py start` (fixed 2026-10-31: hosted runtimes start the container from `/`, not the Dockerfile's WORKDIR). `backend/fly.toml` is prepared:

```bash
cd backend
fly launch --no-deploy --copy-config      # creates the app, reads fly.toml
fly secrets set LIVEKIT_URL=wss://gimli-bakar-rcjx7kir.livekit.cloud \
               LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... \
               DEEPGRAM_API_KEY=... MURF_API_KEY=...
fly deploy
fly logs                                   # wait for "registered worker"
```

Notes:

- There is deliberately **no `[http_service]`** in `fly.toml` — the worker dials out to LiveKit and needs no inbound traffic or health checks.
- Secrets are set via `fly secrets`, never committed. `BAKAR_LLM` / `BAKAR_LLM_MODEL` are non-secret and live in `fly.toml`'s `[env]`.
- One `shared-cpu-1x` with 1 GB handles several concurrent sessions; scale with `fly scale count 2` if needed.

### Railway instead

`backend/railway.toml` is configured for the Dockerfile (`builder = "DOCKERFILE"`), because nixpacks cannot be relied on to provision `uv`. Create a Railway service from the repo with **root directory `backend`**, then set the same secrets in the service's Variables tab.

## 5. Run the worker on your own hardware (old laptop / mini PC)

A machine that stays plugged in and awake is a perfectly good home for the worker — it only
dials **out** to LiveKit on port 443, so no port forwarding, no public IP, no DNS.

What it must survive is everything that happens *unattended*: a crash, a Windows Update reboot,
a power blip. `backend/scripts/run-agent-watchdog.ps1` covers that:

- starts the worker in production mode (`start`, not `dev`)
- restarts it within ~15 s if it dies
- refuses to start a second worker against the same LiveKit project
- keeps the worker stopped during a daily maintenance window, then resumes
- optionally runs `git pull` + `uv sync` on every start — push to GitHub, restart, deployed
- logs to `backend/logs/watchdog-YYYYMMDD.log` and one file per worker run

### Install (once, in an Administrator PowerShell)

```powershell
# 1. never sleep, ignore the lid
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /S SCHEME_CURRENT

# 2. start the watchdog on every boot, before anyone logs in
schtasks /Create /TN "Bakar agent watchdog" /SC ONSTART /RU SYSTEM /RL HIGHEST ^
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File S:\Bakar\backend\scripts\run-agent-watchdog.ps1 -UvPath C:\Users\<you>\.local\bin\uv.exe -MaintenanceStartHour 4 -MaintenanceMinutes 60"
```

Adjust `-MaintenanceStartHour` to your quietest hour (24h clock). `-MaintenanceMinutes 0` disables
the window. Remove with `schtasks /Delete /TN "Bakar agent watchdog" /F`.

### What this setup costs you

- **Money:** electricity only — an idle laptop draws roughly 15–30 W, on the order of ₹100–150/month.
- **Availability:** every maintenance window and every unplanned reboot is silence for visitors,
  because a room with no registered worker simply has nobody in it. Choose the window at your
  lowest-traffic hour, and treat the "agent unavailable" toast as a prerequisite before sharing
  the link widely.
- **Attention:** dust cleaning every few months; the battery will age faster if left at 100% on
  mains, so cap the charge in the vendor's power tool if it offers one.

For reference, LiveKit Cloud's free **Build** plan includes 1 agent deployment and 1,000 agent
session minutes per month — the same job with no hardware to babysit. The laptop route makes
sense when you want your own provider keys and zero platform spend; the managed route makes
sense when uptime matters more than a few hundred rupees.

## 6. Agent on a free VPS (Oracle Cloud / GCP)

The self-hosting route: your own keys, no plan limits, and room for a second agent (MunshiJi)
on the same box. `backend/docker-compose.yml` is ready.

**Sizing, measured on a running worker (not guessed):** the two-process tree idles at
**~1.1 GB resident** with models loaded; live sessions add audio buffers on top.

| Free option | RAM | Verdict |
|---|---|---|
| Oracle Cloud Always Free — ARM A1 (up to 4 OCPU / 24 GB total) | plenty | **best** — verified: every Python dependency (incl. `livekit-blingfire` cp313 aarch64) ships an ARM Linux wheel for our pinned versions |
| GCP free tier — e2-micro | 1 GB | **will OOM** — below the measured idle footprint; also US-only regions |
| Oracle free x86 micro | 1 GB | same RAM problem |

**Region matters for a voice agent.** The LiveKit project sits in **India South**, so the worker
should be in `ap-mumbai-1` (or Hyderabad) — the worker's leg of the audio path is
machine ↔ LiveKit, and a US VPS adds ~100 ms one-way to every turn. Caveat: Oracle's free ARM
capacity in Mumbai is contested ("out of capacity" on create is common) and the account needs a
card for verification; instances reported idle can be reclaimed.

**Deploy (from `backend/` on the VPS):**

```bash
git clone <your-repo> bakar && cd bakar/backend
nano .env                     # same values as the Agent column of the matrix
docker compose up -d --build
docker compose logs -f        # wait for: registered worker {"agent_name": "bakar-agent"}
```

`restart: unless-stopped` is the process manager — the container comes back after crashes and
reboots on its own. There is **nothing to open in the firewall**: the container only makes
outbound connections on 443 (WSS) and UDP for media. The one environment note: create `.env`
on the VPS (compose reads it); the repo's `.env.local` files are for local runs and are
gitignored.

Two agents on one free VM: add a second service with a different `AGENT_NAME`
(e.g. `munshiji-agent`) and its own env — the 24 GB ARM allotment fits both easily.

## 7. Post-deploy verification

Run these in order; each one proves a layer:

| Check | Command / action | Proves |
|---|---|---|
| Token endpoint | `curl -X POST https://<frontend>/api/token` → 200 + `roomName` | Frontend env is complete |
| Worker registered | `fly logs` (or Railway deploy logs) shows `registered worker {"agent_name": "bakar-agent"}` | Agent is connected |
| Dispatch | `curl … /api/token` again → open `https://<frontend>` and press START TALKING | Agent joins the room and greets within ~2 s |
| End-to-end | Speak, then press END CALL | Recap card appears |
| Phone | Place a call to the SIP number | Inbound practice line |

If the token endpoint returns `500 {"error":"Server is missing AGENT_NAME"}`, an env var is missing on the host — the route fails loudly by design so a broken deploy cannot masquerade as a working one.

## 8. Environment variable matrix

| Variable | Frontend | Agent |
|---|---|---|
| `LIVEKIT_URL` | ✅ | ✅ |
| `LIVEKIT_API_KEY` | ✅ | ✅ |
| `LIVEKIT_API_SECRET` | ✅ | ✅ |
| `AGENT_NAME` (`bakar-agent`) | ✅ required | — (it *is* the agent) |
| `DEEPGRAM_API_KEY` | — | ✅ |
| `MURF_API_KEY` | — | ✅ |
| `BAKAR_LLM`, `BAKAR_LLM_MODEL` | — | optional (defaults are correct) |
| `SELORA_API_KEY`, `SELORA_BASE_URL` | — | optional |

No agent uses `GOOGLE_API_KEY`: the LLM is selected by `BAKAR_LLM` (default `livekit`, i.e. LiveKit's inference gateway), so no Google key is required anywhere in the repo.

## 9. Security, stated plainly

- `/api/token` is **unauthenticated by design**. It now carries an in-memory per-IP rate limit (20 requests/hour), but that counter lives per instance — on serverless each instance counts separately, so it throttles accidents, not abuse. Deployment Protection (or keeping the URL private) remains the real gate until a shared-store limiter exists.
- Keys are host-side only: `LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `MURF_API_KEY` are never sent to the browser; only the minted 15-minute JWT leaves the server.
- `.env.local` files are gitignored and excluded from CLI uploads; do not move the values into `next.config.ts` or any committed file.

## 10. What was verified before writing this

- `next.config.ts` change (runtime tracing of `public/`) builds cleanly and keeps the logo and social-card assets available in serverless bundles.
- All added TOML files parse.
- Docker is not installed on this machine, so the agent image build and a real Fly deploy have **not** been executed here. The Dockerfile's CMD was fixed on 2026-10-31 to absolute paths (`/app/.venv/bin/python /app/src/agent.py start`) after the first LiveKit Cloud deploy; the Fly config uses it as-is.
