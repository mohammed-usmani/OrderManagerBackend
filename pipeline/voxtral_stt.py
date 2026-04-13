"""Custom Voxtral STT service for Pipecat.

Wraps the Mistral API's transcription endpoint to provide
speech-to-text compatible with the Pipecat pipeline.
"""

import io
import wave
from typing import AsyncGenerator, Optional

from loguru import logger
from mistralai.client import Mistral

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.utils.time import time_now_iso8601


class VoxtralSTTService(SegmentedSTTService):
    """Voxtral STT service using the Mistral transcription API.

    Receives audio segments from VAD and transcribes them using
    Mistral's Voxtral transcription model.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "voxtral-mini-transcribe-2507",
        language: str = "en",
        **kwargs,
    ):
        """Initialize Voxtral STT service.

        Args:
            api_key: Mistral API key.
            model: Transcription model to use.
            language: Language code for transcription.
            **kwargs: Additional arguments passed to SegmentedSTTService.
        """
        super().__init__(**kwargs)
        self._client = Mistral(api_key=api_key)
        self._model = model
        self._language = language

    def can_generate_metrics(self) -> bool:
        return True

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Transcribe audio using Mistral's transcription API.

        Args:
            audio: Raw PCM audio bytes from the pipeline.

        Yields:
            TranscriptionFrame with the transcribed text, or ErrorFrame.
        """
        try:
            await self.start_processing_metrics()

            # Wrap raw PCM as WAV for the API
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self._sample_rate or 16000)
                wf.writeframes(audio)
            wav_bytes = wav_buffer.getvalue()

            response = await self._client.audio.transcriptions.complete_async(
                model=self._model,
                file={
                    "file_name": "audio.wav",
                    "content": wav_bytes,
                    "content_type": "audio/wav",
                },
                language=self._language,
            )

            await self.stop_processing_metrics()

            text = response.text.strip()

            if text:
                logger.debug(f"Voxtral STT transcription: [{text}]")
                yield TranscriptionFrame(
                    text=text,
                    user_id="",
                    timestamp=time_now_iso8601(),
                )
            else:
                logger.warning("Voxtral STT: empty transcription")

        except Exception as e:
            logger.error(f"Voxtral STT error: {e}")
            yield ErrorFrame(error=f"Voxtral STT error: {e}")
