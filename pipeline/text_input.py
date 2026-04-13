"""Text input processor for injecting text messages into the voice pipeline.

Intercepts TextFrames (from typed chat) and converts them to
TranscriptionFrames so the LLM context aggregator treats them
the same as speech-to-text output.
"""

from loguru import logger

from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class TextInputProcessor(FrameProcessor):
    """Converts incoming TextFrames into TranscriptionFrames.

    When a client sends a text message (encoded as a protobuf TextFrame),
    this processor intercepts it and re-emits it as a TranscriptionFrame
    so the downstream LLM context aggregator processes it like spoken input.
    All other frame types pass through unchanged.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame) and frame.text:
            logger.debug(f"TextInputProcessor: converting text to transcription [{frame.text}]")
            transcription = TranscriptionFrame(
                text=frame.text,
                user_id="web-user",
                timestamp="",
            )
            await self.push_frame(transcription, direction)
        else:
            await self.push_frame(frame, direction)
