# Gemini Live Native Audio (feature branch)

This branch swaps the voice stack from **Voxtral STT + Mistral/Groq LLM +
Voxtral TTS** to a single **Google Gemini Live Native Audio** service. Gemini
handles speech-to-text, LLM reasoning, and text-to-speech inside one
WebSocket session.

## Why

- Lower latency (one hop instead of three).
- Better prosody / emotional awareness (native audio → native audio).
- Simpler pipeline: `transport.input → user → gemini → transport.output → assistant`.

## Setup

1. Get a key at <https://aistudio.google.com/> (free tier is fine to start).
2. Add to `.env`:

   ```env
   GOOGLE_API_KEY=...

   # Optional overrides — defaults shown.
   GEMINI_MODEL=models/gemini-2.5-flash-native-audio-preview-12-2025
   GEMINI_VOICE=Charon
   ```

3. Restart the backend. Client needs no changes — sample rates match.

## What's different in the pipeline

- `VoxtralSTTService`, `FallbackLLMService`, `VoxtralTTSService` are
  *unused* on this branch (files still exist for easy revert).
- `GeminiLiveLLMService(api_key=..., tools=..., settings=...)` replaces all
  three.
- Output audio is **24 kHz mono PCM16** (same as before, so the browser
  player works unchanged).
- System instruction is fresh per connection (time-context block prepended),
  but **can't be mutated mid-session** — Gemini Live requires a reconnect.

## Things to watch

- Model is still in **preview** (Dec 2025). Expect breaking changes on
  Google's side.
- Free-tier session length caps at ~15 minutes. Long sessions need
  `SessionResumptionConfig` (the service supports it; we haven't wired it
  up yet).
- Quotas: ~3 concurrent free / ~50 concurrent Tier-1.

## Rollback

```bash
git checkout main
```

All Voxtral + Mistral/Groq code is intact on `main`.
