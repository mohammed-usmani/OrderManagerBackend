# Gemini Live Native Audio

The voice agent runs on a single **Google Gemini Live Native Audio** service.
It replaced the original **Voxtral STT + Mistral/Groq LLM + Voxtral TTS**
stack: Gemini handles speech understanding, reasoning and speech output
inside one WebSocket session.

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
   GEMINI_MODEL=models/gemini-3.1-flash-live-preview
   GEMINI_VOICE=Charon
   ```

3. Restart the backend. Client needs no changes — sample rates match.

## What's different in the pipeline

- `VoxtralSTTService`, `FallbackLLMService` and `VoxtralTTSService` have been
  removed from the codebase.
- `GeminiLiveLLMService(api_key=..., tools=..., settings=...)` replaces all
  three.
- Output audio is **24 kHz mono PCM16** (same as before, so the browser
  player works unchanged).
- System instruction is fresh per connection (time-context block prepended),
  but **can't be mutated mid-session** — Gemini Live requires a reconnect.

## Things to watch

- The default model is a **preview** model. Expect breaking changes on
  Google's side.
- Free-tier session length caps at ~15 minutes. Long sessions need
  `SessionResumptionConfig` (the service supports it; we haven't wired it
  up yet).
- Quotas: ~3 concurrent free / ~50 concurrent Tier-1. The server enforces
  this with `MAX_CONCURRENT_CALLS` (default 3) and caps each call at
  `MAX_SESSION_SECONDS` (default 900).

## Going back to Voxtral + Mistral/Groq

The old services were removed once Gemini Live became the only engine. They
are in git history: `git show 980a54c^:pipeline/voice_pipeline.py` has the last
pipeline that wired them together, and the service classes live in
`pipeline/voxtral_stt.py`, `pipeline/voxtral_tts.py` and
`pipeline/fallback_llm.py` at that commit. Restoring them also needs the
`groq` and `mistral` extras on `pipecat-ai` and `MISTRAL_API_KEY`,
`GROQ_API_KEY` and `VOICE_ID`.
