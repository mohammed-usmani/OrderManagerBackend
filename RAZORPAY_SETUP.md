# Razorpay (Test Mode) setup

Online payments use **Razorpay in Test Mode** — no real money moves. When the
keys below are unset the app simply hides "Pay online" and offers cash only.

## 1. Get test API keys
1. Create a free account at https://dashboard.razorpay.com and sign in.
2. Flip the dashboard to **Test Mode** (toggle in the top bar).
3. Go to **Settings → API Keys → Generate Test Key**.
4. Copy the **Key Id** (`rzp_test_…`) and the **Key Secret** (shown once).

## 2. Backend env (`server/.env` and Cloud Run `server/env.cloudrun.yaml`)
```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_test_key_secret
RAZORPAY_WEBHOOK_SECRET=any_long_random_string   # set the same value in step 4
```
Restart the API (locally) or run `./deploy.sh` (Cloud Run) so it picks them up.

## 3. Frontend env (`client/.env.local` and Vercel project env)
```
NEXT_PUBLIC_RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx   # same Key Id as above
```
Redeploy the frontend (or `npm run dev`). The Key Secret is **never** exposed to
the browser — only the Key Id is public.

## 4. Webhook (optional but recommended)
1. Dashboard (Test Mode) → **Settings → Webhooks → Add New Webhook**.
2. URL: `https://<your-api-domain>/payments/webhook`
   (e.g. `https://saffron-smoke-api-rq7uctzdla-el.a.run.app/payments/webhook`).
3. Secret: paste the same string you used for `RAZORPAY_WEBHOOK_SECRET`.
4. Subscribe to events: **`payment.captured`** and **`payment.failed`**.

The webhook makes settlement reliable even if the customer closes their browser
right after paying — the server still marks the order paid (idempotent with the
in-browser verify callback).

## 5. Test it
On the checkout screen choose **Pay online** and use any Razorpay test
instrument:
- **UPI:** `success@razorpay` (use `failure@razorpay` to test a failed payment)
- **Card:** `4111 1111 1111 1111`, any future expiry, any CVV, any name

A successful test payment marks the order/table **paid**, frees the table, and
shows up in the dashboard revenue — all without real money.

## How it's wired (for reference)
- `GET /payments/config` → `{ razorpay_enabled, key_id }` (UI feature-flag)
- `POST /payments/razorpay/order` → creates a Razorpay order (public; funds go to
  the restaurant) → browser opens Checkout
- `POST /payments/razorpay/verify` → verifies the signature, marks paid
- `POST /payments/webhook` → server-to-server confirmation (signed)
- `POST /payments/cash` → cashier/manager records a cash settlement
