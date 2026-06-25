from pathlib import Path

from app.config import settings


class ChatterboxService:
    def __init__(self):
        self._model = None
        self._available = False
        try:
            from chatterbox.tts import ChatterboxTTS  # type: ignore

            self._model = ChatterboxTTS.from_pretrained(device="cpu")
            self._available = True
        except Exception:
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def synthesize(self, text: str, voice_prompt_path: str | None = None, exaggeration: float = 0.5, cfg_weight: float = 0.5) -> str:
        output_path = Path(settings.audio_storage_path) / "latest.wav"
        if not self._available:
            output_path.write_bytes(b"")
            return str(output_path)

        import torchaudio as ta  # type: ignore

        wav = self._model.generate(text, audio_prompt_path=voice_prompt_path, exaggeration=exaggeration, cfg_weight=cfg_weight)
        ta.save(str(output_path), wav, self._model.sr)
        return str(output_path)


chatterbox_service = ChatterboxService()

