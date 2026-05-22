"""Gemini Live API integration for assistant voice playback."""

from __future__ import annotations

import base64
import json
import os
import struct
import urllib.parse
from typing import Any

import httpx
import websockets

GEMINI_LIVE_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
GEMINI_GENERATE_CONTENT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
DEFAULT_GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
DEFAULT_GEMINI_TRANSCRIPTION_MODEL = os.getenv("GEMINI_TRANSCRIPTION_MODEL", "gemini-2.5-flash-lite")
DEFAULT_GEMINI_LIVE_VOICE = os.getenv("GEMINI_LIVE_VOICE", "Kore")
GEMINI_OUTPUT_RATE = 24000
GEMINI_INPUT_AUDIO_CHUNK_BYTES = 32_000


class GeminiLiveError(RuntimeError):
    pass


def _wav_header(pcm_size: int, *, sample_rate: int = GEMINI_OUTPUT_RATE, channels: int = 1, sample_width: int = 2) -> bytes:
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + pcm_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, sample_width * 8),
            b"data",
            struct.pack("<I", pcm_size),
        ]
    )


def pcm_to_wav(pcm: bytes) -> bytes:
    return _wav_header(len(pcm)) + pcm


def _build_ws_url(api_key: str) -> str:
    return f"{GEMINI_LIVE_WS_URL}?key={urllib.parse.quote(api_key)}"


def _build_setup_message(*, voice: str | None = None) -> dict[str, Any]:
    return {
        "setup": {
            "model": f"models/{DEFAULT_GEMINI_LIVE_MODEL}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice or DEFAULT_GEMINI_LIVE_VOICE,
                        }
                    }
                },
            },
            "outputAudioTranscription": {},
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "You are the voice of MediAssist AI. Read assistant messages clearly, naturally, "
                            "and warmly. Do not add new appointment details or medical advice; speak only the "
                            "provided assistant message."
                        )
                    }
                ]
            },
        }
    }


def _build_transcription_setup_message() -> dict[str, Any]:
    return {
        "setup": {
            "model": f"models/{DEFAULT_GEMINI_LIVE_MODEL}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
            },
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "disabled": True,
                }
            },
            "inputAudioTranscription": {},
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Transcribe the user's appointment scheduling request. Return only the words the user spoke."
                        )
                    }
                ]
            },
        }
    }


def _chunk_base64_audio(audio_base64: str, *, chunk_bytes: int = GEMINI_INPUT_AUDIO_CHUNK_BYTES) -> list[str]:
    audio = base64.b64decode(audio_base64)
    return [base64.b64encode(audio[i : i + chunk_bytes]).decode("ascii") for i in range(0, len(audio), chunk_bytes)]


async def synthesize_assistant_speech(*, text: str, voice: str | None = None) -> bytes:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiLiveError("GEMINI_API_KEY is not set")

    url = GEMINI_GENERATE_CONTENT_URL.format(model=urllib.parse.quote(DEFAULT_GEMINI_TTS_MODEL))
    payload: dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Read exactly and only the transcript between the quotes. "
                            "Do not add words. Do not apologize. Do not ask follow-up questions. "
                            "Do not mention preferences, gender, location, or availability unless those exact words are in the transcript. "
                            f'Transcript: "{text}"'
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice or DEFAULT_GEMINI_LIVE_VOICE,
                    }
                }
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{url}?key={urllib.parse.quote(api_key)}", json=payload)
            if response.status_code >= 400:
                raise GeminiLiveError(f"Gemini TTS error {response.status_code}: {response.text}")
            data = response.json()
    except Exception as exc:
        if isinstance(exc, GeminiLiveError):
            raise
        raise GeminiLiveError(f"Gemini TTS failed: {exc}") from exc

    audio_chunks: list[bytes] = []
    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline_data = part.get("inlineData") or {}
            audio_data = inline_data.get("data")
            if audio_data:
                audio_chunks.append(base64.b64decode(audio_data))

    if not audio_chunks:
        raise GeminiLiveError("Gemini TTS returned no audio")

    return pcm_to_wav(b"".join(audio_chunks))


async def transcribe_user_audio(*, audio_base64: str, mime_type: str = "audio/pcm;rate=16000") -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiLiveError("GEMINI_API_KEY is not set")

    # The UI records raw 16 kHz PCM. Gemini generateContent supports WAV for
    # audio understanding, so wrap the PCM bytes before sending the transcript request.
    pcm_audio = base64.b64decode(audio_base64)
    wav_audio_base64 = base64.b64encode(pcm_to_wav(pcm_audio)).decode("ascii")
    url = GEMINI_GENERATE_CONTENT_URL.format(model=urllib.parse.quote(DEFAULT_GEMINI_TRANSCRIPTION_MODEL))
    payload: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Generate a transcript of the speech in this audio. "
                            "Return only the spoken words, without timestamps, labels, summaries, or translations."
                        )
                    },
                    {
                        "inlineData": {
                            "mimeType": "audio/wav",
                            "data": wav_audio_base64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{url}?key={urllib.parse.quote(api_key)}", json=payload)
            if response.status_code >= 400:
                raise GeminiLiveError(f"Gemini transcription error {response.status_code}: {response.text}")
            data = response.json()
    except Exception as exc:
        if isinstance(exc, GeminiLiveError):
            raise
        raise GeminiLiveError(f"Gemini transcription failed: {exc}") from exc

    transcript_parts: list[str] = []
    for candidate in data.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if part.get("text"):
                transcript_parts.append(part["text"])

    transcript = " ".join(part.strip() for part in transcript_parts if part.strip()).strip()
    if not transcript:
        raise GeminiLiveError("Gemini returned no transcript")
    return transcript
