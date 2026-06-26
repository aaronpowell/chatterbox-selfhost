import importlib.util
import logging
from pathlib import Path

from app.config import settings
from app.observability import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


class ChatterboxService:
    def __init__(self):
        self._model = None
        # Lightweight availability check: is the optional `tts` extra installed?
        # We deliberately DON'T load the (multi-GB) model here so app startup and
        # uvicorn reloads stay fast. The model is loaded lazily on first use.
        self._available = importlib.util.find_spec("chatterbox") is not None

    @property
    def is_available(self) -> bool:
        return self._available

    def _ensure_model(self):
        if self._model is None:
            with tracer.start_as_current_span("tts.load_model"):
                logger.info("Loading Chatterbox TTS model into memory.")
                from chatterbox.tts import ChatterboxTTS  # type: ignore

                self._model = ChatterboxTTS.from_pretrained(device="cpu")
        return self._model

    def synthesize(self, text: str, voice_prompt_path: str | None = None, exaggeration: float = 0.5, cfg_weight: float = 0.5) -> str:
        with tracer.start_as_current_span("tts.synthesize") as span:
            span.set_attribute("tts.text.length", len(text))
            span.set_attribute("tts.exaggeration", exaggeration)
            span.set_attribute("tts.cfg_weight", cfg_weight)
            span.set_attribute("tts.has_voice_prompt", voice_prompt_path is not None)

            output_path = Path(settings.audio_storage_path) / "latest.wav"
            if not self._available:
                output_path.write_bytes(b"")
                return str(output_path)

            import torchaudio as ta  # type: ignore

            model = self._ensure_model()
            wav = model.generate(text, audio_prompt_path=voice_prompt_path, exaggeration=exaggeration, cfg_weight=cfg_weight)
            ta.save(str(output_path), wav, model.sr)
            logger.info("Saved synthesized audio to %s", output_path)
            span.set_attribute("tts.output_path", str(output_path))
            return str(output_path)


chatterbox_service = ChatterboxService()
