"""Custom Voxtral TTS service for Pipecat.

Wraps the Mistral API's Voxtral TTS model to produce audio frames
compatible with the Pipecat pipeline.
"""

import base64
import io
import wave
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from loguru import logger
from mistralai.client import Mistral

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts


@dataclass
class VoxtralTTSSettings(TTSSettings):
    """Settings for VoxtralTTSService."""

    pass


class VoxtralTTSService(TTSService):
    """Voxtral TTS service using the Mistral API.

    Uses Mistral's Voxtral mini TTS model to synthesize speech.
    Outputs PCM audio at 24kHz sample rate.
    """

    VOXTRAL_SAMPLE_RATE = 24000
    DEFAULT_VOICE_ID = "98559b22-62b5-4a64-a7cd-fc78ca41faa8"

    Settings = VoxtralTTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        api_key: str,
        voice_id: Optional[str] = DEFAULT_VOICE_ID,
        sample_rate: int = VOXTRAL_SAMPLE_RATE,
        settings: Optional[Settings] = None,
        **kwargs,
    ):
        """Initialize Voxtral TTS service.

        Args:
            api_key: Mistral API key.
            voice_id: Mistral voice ID to use. If None, no voice_id is sent
                and the API uses its default voice.
            sample_rate: Audio sample rate. Defaults to 24000.
            settings: Runtime-updatable settings.
            **kwargs: Additional arguments passed to TTSService.
        """
        default_settings = self.Settings(
            model="voxtral-mini-tts-2603",
            voice=voice_id or self.DEFAULT_VOICE_ID,
            language="en",
        )

        if settings is not None:
            default_settings.apply_update(settings)

        super().__init__(
            pause_frame_processing=True,
            push_start_frame=True,
            push_stop_frames=True,
            sample_rate=sample_rate,
            settings=default_settings,
            **kwargs,
        )

        self._client = Mistral(api_key=api_key)
        self._voice_id = voice_id

    def can_generate_metrics(self) -> bool:
        return True

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Generate speech from text using Voxtral TTS.

        Args:
            text: The text to synthesize.
            context_id: Context ID for tracking frames.

        Yields:
            TTSAudioRawFrame with synthesized audio data.
        """
        logger.debug(f"{self}: Generating TTS [{text}]")

        try:
            kwargs = {
                "model": self._settings.model,
                "input": text,
                "response_format": "wav",
            }
            if self._voice_id:
                kwargs["voice_id"] = self._voice_id

            response = await self._client.audio.speech.complete_async(**kwargs)

            await self.stop_ttfb_metrics()

            audio_bytes = base64.b64decode(response.audio_data)

            with wave.open(io.BytesIO(audio_bytes)) as w:
                channels = w.getnchannels()
                frame_rate = w.getframerate()
                num_frames = w.getnframes()
                pcm_data = w.readframes(num_frames)
                yield TTSAudioRawFrame(
                    pcm_data, frame_rate, channels, context_id=context_id
                )

        except Exception as e:
            logger.error(f"{self}: Voxtral TTS error: {e}")
            yield ErrorFrame(error=f"Voxtral TTS error: {e}")
