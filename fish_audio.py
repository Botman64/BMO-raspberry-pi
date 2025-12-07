"""Lightweight Fish Audio API client for text-to-speech output."""

import os
import tempfile
import time
from typing import Generator, Optional

import requests


class FishAudioClient:
    """Client wrapper for Fish Audio TTS endpoints.

    The client exchanges GPT-style text for synthesized audio clips.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        speaker_id: Optional[str] = None,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.environ.get("FISH_AUDIO_API_KEY")
        self.base_url = (base_url or os.environ.get("FISH_AUDIO_BASE_URL") or "https://api.fish.audio/v1").rstrip("/")
        self.model = model or os.environ.get("FISH_AUDIO_MODEL", "gpt_sovits")
        self.speaker_id = speaker_id or os.environ.get("FISH_AUDIO_SPEAKER_ID")
        self.timeout = timeout
        self.retries = retries

    def synthesize_to_path(self, text: str) -> str:
        """Return a local audio file path for the synthesized text.

        A temporary file is written so existing audio playback utilities can
        operate on a path. Callers are responsible for deleting the returned
        file when done.
        """

        response = self._post_tts(text, stream=True)
        suffix = self._infer_extension(response.headers.get("Content-Type"))
        fd, path = tempfile.mkstemp(suffix=suffix or ".wav")
        with os.fdopen(fd, "wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return path

    def synthesize_stream(self, text: str) -> Generator[bytes, None, None]:
        """Stream raw audio bytes for the provided text."""

        response = self._post_tts(text, stream=True)
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    def _post_tts(self, text: str, stream: bool) -> requests.Response:
        if not self.api_key:
            raise RuntimeError("FISH_AUDIO_API_KEY is required to call Fish Audio")

        payload = {"text": text, "model": self.model}
        if self.speaker_id:
            payload["speaker_id"] = self.speaker_id

        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/tts"

        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=self.timeout, stream=stream)
                response.raise_for_status()
                return response
            except Exception as exc:  # pragma: no cover - defensive retry
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1)
                else:
                    raise
        raise RuntimeError(f"Failed to reach Fish Audio: {last_error}")

    @staticmethod
    def _infer_extension(content_type: Optional[str]) -> Optional[str]:
        if not content_type:
            return None
        if "wav" in content_type:
            return ".wav"
        if "mpeg" in content_type or "mp3" in content_type:
            return ".mp3"
        if "ogg" in content_type:
            return ".ogg"
        return None
