# Deploying Saffron & Smoke to Cloud Run (first-timer guide)

**Architecture:** the **frontend** stays on Vercel; only the **backend** (this
container) runs on **Cloud Run**. Voice is **Gemini Live Native Audio** — one
WebSocket does STT + LLM + TTS together, so there's **no separate Speech-to-Text
or Text-to-Speech service** to set up or pay for.

Cloud Run = "run my container, give it an HTTPS URL, scale it to zero when
idle." You pay only while it's handling requests.

---

## What you need to provision (all have free tiers, all scale-to-zero friendly)

| Need        | Use                          | Why                                                        |
|-------------|------------------------------|-----------------------------------------------------------|
| Postgres    | **Neon** (or Supabase)       | Free tier, supports `pgvector`. Avoid Cloud SQL (24/7 bill). |
| Redis       | **Upstash Redis**            | Serverless, free tier, `rediss://` URL. (Holds WS tickets.) |
| Voice + LLM | **Google AI Studio** key     | Gemini Live (audio in/out) + the model. Pay-per-use.       |
| Embeddings  | **Mistral** key *(optional)* | Semantic menu search; without it, search is keyword-only.  |
| Images      | **Cloudinary** *(optional)*  | Menu photo uploads; without it admins paste image URLs.    |

> Redis is effectively **required** — the voice line mints a short-lived ticket
> in Redis before opening the WebSocket. No Redis → no voice. Upstash free is
> perfect and stays at ₹0 idle.

---

## Step 1 — Provision the database (Neon)

1. Sign up at neon.tech → **Create project** (pick region close to you, e.g.
   Singapore/Mumbai).
2. It gives you a **connection string** like:
   `postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
   — copy it. (Prefer the **Pooled** connection string if shown.)
3. pgvector is supported out of the box — our app runs `CREATE EXTENSION vector`
   automatically on first boot, and Neon allows it. Nothing to do here.

Save that string as your **`DATABASE_URL`**.

## Step 2 — Provision Redis (Upstash)

1. Sign up at upstash.com → **Create Database** (Redis), pick a nearby region.
2. Copy the connection URL in the form `rediss://default:PASSWORD@host:port`
   (the TLS one). Save it as your **`REDIS_URL`**.

## Step 3 — Get the API keys

- **`GOOGLE_API_KEY`** — aistudio.google.com → *Get API key*. (This powers the
  whole voice experience.)
- **`MISTRAL_API_KEY`** *(optional)* — console.mistral.ai → API keys.
- **`CLOUDINARY_URL`** *(optional)* — cloudinary.com dashboard →
  `cloudinary://<key>:<secret>@<cloud-name>`.

---

## Step 4 — Install & set up gcloud (one time)

1. Install the CLI: https://cloud.google.com/sdk/docs/install
2. Log in and pick your project:
   ```bash
   gcloud auth login
   gcloud projects list                       # find your PROJECT_ID
   gcloud config set project YOUR_PROJECT_ID
   gcloud config set run/region asia-south1   # Mumbai (or asia-southeast1)
   ```
   > Tip: in this chat you can run an interactive login by typing
   > `! gcloud auth login` in the prompt.
3. Enable the services Cloud Run needs:
   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```

## Step 5 — Set a budget alert FIRST (protect your credits)

GCP Console → **Billing → Budgets & alerts → Create budget** → set ₹16,000 with
email alerts at 50% / 90% / 100%. (GCP won't auto-stop, but you'll know early.)

## Step 6 — Deploy 🚀

From the **`server/`** folder (Cloud Run sees the `Dockerfile` and builds it for
you — no manual `docker push` needed):

```bash
cd RestaurantOrderManager/server

gcloud run deploy saffron-smoke-api \
  --source . \
  --allow-unauthenticated \
  --memory 2Gi --cpu 1 --cpu-boost \
  --timeout 3600 \
  --min-instances 0 --max-instances 3 \
  --set-env-vars "DATABASE_URL=postgresql://USER:PASS@HOST/db?sslmode=require" \
  --set-env-vars "^@^REDIS_URL=rediss://default:PASS@HOST:PORT" \
  --set-env-vars "GOOGLE_API_KEY=YOUR_GOOGLE_KEY" \
  --set-env-vars "MISTRAL_API_KEY=YOUR_MISTRAL_KEY" \
  --set-env-vars "JWT_SECRET_KEY=$(openssl rand -hex 32)" \
  --set-env-vars "ADMIN_EMAIL=you@example.com" \
  --set-env-vars "ADMIN_PASSWORD=pick-a-strong-password"
```

The first build takes a few minutes (it's a ~2.5 GB AI image). When it finishes
you'll get a URL like `https://saffron-smoke-api-xxxxx.asia-south1.run.app`.

**Why each flag:**
- `--source .` → builds from our Dockerfile via Cloud Build.
- `--allow-unauthenticated` → the API is public (your customers aren't logged in).
- `--timeout 3600` → a voice call holds the WebSocket open; don't cut it off.
- `--memory 2Gi --cpu-boost` → the image loads heavy AI libs; this boots faster.
- `--max-instances 3` → safety cap so nothing can fan out and burn credits.
- `--min-instances 0` → scale to zero = ₹0 idle (accept a few-sec first call).
- `^@^...REDIS_URL=...` → the `^@^` changes the value separator to `@` just for
  that one var, so the `@` inside the Redis URL isn't misread. (Commas in URLs
  would need the same trick.)

> **Secrets, the cleaner way (optional):** instead of `--set-env-vars`, store
> keys in Secret Manager and use `--set-secrets "GOOGLE_API_KEY=google-key:latest,..."`.

### Migrations
The container runs `alembic upgrade head` on boot (creates tables + the pgvector
extension + seeds the menu/areas/admin). Nothing extra to do. To run migrations
separately instead, deploy with `--set-env-vars RUN_MIGRATIONS=false` and run
them yourself against `DATABASE_URL`.

## Step 7 — Point the Vercel frontend at it

In your Vercel project → **Settings → Environment Variables**:
```
NEXT_PUBLIC_API_URL = https://saffron-smoke-api-xxxxx.asia-south1.run.app
NEXT_PUBLIC_WS_URL  = wss://saffron-smoke-api-xxxxx.asia-south1.run.app/ws
```
Note **`wss://`** (secure WebSocket) for the WS URL. Redeploy the frontend.

## Step 8 — Test

```bash
curl https://saffron-smoke-api-xxxxx.asia-south1.run.app/health   # {"status":"ok"}
```
Open your Vercel site → click **Order** → the first call shows "Starting…" while
the container cold-starts, then Arjun picks up. 🎙️

---

## Updating after code changes
Just re-run the same deploy command:
```bash
cd RestaurantOrderManager/server && gcloud run deploy saffron-smoke-api --source .
```
(Env vars persist across deploys; only pass `--set-env-vars` when changing them.)

## Cold starts (this is the ₹0-idle tradeoff)
Scale-to-zero means the first request after idle waits a few seconds while the
container boots. Already handled in the UX: the frontend shows a loading state
on the **Start call** click and pings `/health` on page load to warm it. If you
ever want guaranteed-instant starts while actively demoing, add
`--min-instances 1` (small always-on cost) and set it back to `0` when done.

## Quick troubleshooting
- **Voice won't connect / ws-ticket 500** → `REDIS_URL` missing or wrong (must be
  the `rediss://` TLS URL from Upstash).
- **App won't start, DB errors** → check `DATABASE_URL` (needs `?sslmode=require`
  for Neon) in Cloud Run → *Edit & deploy new revision → Variables*.
- **`vector` extension error** → your DB role can't create extensions; on Neon
  it's allowed by default — make sure you used the Neon string, not Cloud SQL.
- **See logs:** `gcloud run services logs read saffron-smoke-api --region asia-south1`
- **Slow first call** → expected cold start; see above.

## What this costs (portfolio scale)
- Idle: **₹0** (scale-to-zero).
- Light demo traffic: a few rupees of Cloud Run + Gemini usage; mostly inside
  free tiers. Neon/Upstash/Vercel free tiers cover the rest.
- The bill scales with *usage*, not with how many projects you host — five
  idle Cloud Run services still cost ~₹0.
