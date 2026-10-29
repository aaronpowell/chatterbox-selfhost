import importlib.util
import logging
from pathlib import Path

from app.config import settings
from app.observability import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


def _resolve_tts_device() -> str:
    configured_device = settings.tts_device
    if configured_device == "cpu":
        return "cpu"

    try:
        import torch  # type: ignore
    except ImportError:
        return "cpu"

    if configured_device == "cuda":
        if torch.cuda.is_available():
            return "cuda"
        logger.warning("TTS_DEVICE is set to cuda but no CUDA device is available; falling back to CPU.")
        return "cpu"

    return "cuda" if torch.cuda.is_available() else "cpu"


class ChatterboxService:
    def __init__(self):
        self._model = None
        self._model_device: str | None = None
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
                self._model_device = _resolve_tts_device()
                logger.info("Loading Chatterbox TTS model into memory on %s.", self._model_device)
                from chatterbox.tts import ChatterboxTTS  # type: ignore

                self._model = ChatterboxTTS.from_pretrained(device=self._model_device)
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

            stage = "import_audio_backend"
            try:
                import torchaudio as ta  # type: ignore

                stage = "load_model"
                logger.info("Speech synthesis stage=%s", stage)
                model = self._ensure_model()
                span.set_attribute("tts.model.device", self._model_device or "unknown")

                stage = "generate_audio"
                logger.info(
                    "Speech synthesis stage=%s device=%s reference_audio=%s text_length=%s",
                    stage, self._model_device, voice_prompt_path, len(text),
                )
                wav = model.generate(
                    text, audio_prompt_path=voice_prompt_path, exaggeration=exaggeration, cfg_weight=cfg_weight,
                )

                stage = "save_audio"
                logger.info("Speech synthesis stage=%s output_path=%s sample_rate=%s", stage, output_path, model.sr)
                ta.save(str(output_path), wav, model.sr)
            except Exception:
                # The API boundary logs the traceback; keep failure context here
                # so it is available even when INFO logs are disabled.
                logger.error(
                    "Speech synthesis failed: stage=%s device=%s reference_audio=%s "
                    "text_length=%s output_path=%s",
                    stage, self._model_device, voice_prompt_path, len(text), output_path,
                )
                raise
            logger.info("Saved synthesized audio to %s", output_path)
            span.set_attribute("tts.output_path", str(output_path))
            return str(output_path)


chatterbox_service = ChatterboxService()
