import importlib.util
from pathlib import Path

from app.config import settings


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
            from chatterbox.tts import ChatterboxTTS  # type: ignore

            self._model = ChatterboxTTS.from_pretrained(device="cpu")
        return self._model

    def synthesize(self, text: str, voice_prompt_path: str | None = None, exaggeration: float = 0.5, cfg_weight: float = 0.5) -> str:
        output_path = Path(settings.audio_storage_path) / "latest.wav"
        if not self._available:
            output_path.write_bytes(b"")
            return str(output_path)

        import torchaudio as ta  # type: ignore

        model = self._ensure_model()
        wav = model.generate(text, audio_prompt_path=voice_prompt_path, exaggeration=exaggeration, cfg_weight=cfg_weight)
        ta.save(str(output_path), wav, model.sr)
        return str(output_path)


chatterbox_service = ChatterboxService()

