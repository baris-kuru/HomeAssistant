"""Text-to-speech using Meta MMS models (lazy-loaded, MPS-accelerated on Apple Silicon)."""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Module-level cache for models and processors
_model_cache: dict[str, object] = {}
_processor_cache: dict[str, object] = {}
_torch_device = None


def _get_device():
    """Determine the torch device (MPS preferred, fallback to CPU)."""
    global _torch_device
    if _torch_device is not None:
        return _torch_device

    try:
        import torch

        if torch.backends.mps.is_available():
            _torch_device = torch.device("mps")
            logger.info("TTS using MPS device (Apple Silicon)")
        else:
            _torch_device = torch.device("cpu")
            logger.info("TTS using CPU device")
    except ImportError:
        _torch_device = torch.device("cpu")
        logger.warning("TTS: torch not available, defaulting to CPU")

    return _torch_device


def _normalize_turkish_text(text: str) -> str:
    """Fix Turkish case normalization issues before tokenization.
    
    The MMS tokenizer uses Python's default .lower() which doesn't handle
    Turkish case conversion properly. This causes:
    - Turkish 'I' (no dot) → 'i' (should be 'ı')
    - Turkish 'İ' (with dot) → 'i' + combining dot (two tokens!)
    
    This function pre-normalizes Turkish text to avoid these issues.
    It only converts Turkish-specific uppercase letters to lowercase.
    """
    if not text:
        return text
    
    # Handle Turkish-specific case conversions
    # Turkish has two types of 'i': 
    # - 'I' (capital, no dot) → 'ı' (lowercase, no dot)
    # - 'İ' (capital, with dot) → 'i' (lowercase, with dot)
    #
    # Python's .lower() incorrectly maps:
    # - 'I' → 'i' (wrong for Turkish)
    # - 'İ' → 'i' + combining dot above U+0307 (two separate characters!)
    #
    # We need to fix both issues.
    
    turkish_case_map = {
        'I': 'ı',   # Turkish capital I → lowercase ı
        'İ': 'i',   # Turkish capital İ → lowercase i
        'Ğ': 'ğ',
        'Ü': 'ü',
        'Ş': 'ş',
        'Ö': 'ö',
        'Ç': 'ç',
    }
    
    result = []
    for char in text:
        if char in turkish_case_map:
            result.append(turkish_case_map[char])
        else:
            result.append(char)
    
    return ''.join(result)


def _load_model(language: str):
    """Lazily load the MMS TTS model for the given language."""
    if language in _model_cache:
        return _model_cache[language], _processor_cache[language]

    model_map = {
        "tr": "facebook/mms-tts-tur",
        "de": "facebook/mms-tts-deu",
        "en": "facebook/mms-tts-eng",
    }

    model_name = model_map.get(language, model_map["en"])
    logger.info(f"Loading MMS TTS model: {model_name} for language: {language}")

    try:
        import torch
        from transformers import VitsModel, AutoTokenizer

        device = _get_device()

        model = VitsModel.from_pretrained(model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name)

        model.to(device)
        model.eval()

        _model_cache[language] = model
        _processor_cache[language] = tokenizer

        logger.info(f"MMS TTS model loaded: {model_name} on {device}")
        return model, tokenizer

    except ImportError as e:
        logger.error(f"TTS dependencies missing: {e}. Install transformers, torch, scipy.")
        return None, None
    except Exception as e:
        logger.error(f"Failed to load MMS TTS model {model_name}: {e}")
        return None, None


def synthesize(text: str, language: str = "en") -> bytes | None:
    """Synthesize text to speech using MMS TTS.

    Args:
        text: The text to synthesize.
        language: Language code ("en" English, "tr" Turkish, "de" German).
                  Unknown languages fall back to English.

    Returns:
        WAV bytes on success, None on failure.
    """
    if not text or not text.strip():
        logger.warning("TTS: empty text, skipping synthesis")
        return None

    # Fallback to English for unknown languages
    if language not in ("tr", "de", "en"):
        logger.warning(f"TTS: unknown language '{language}', falling back to English")
        language = "en"

    # Normalize Turkish text to fix case conversion issues
    original_text = text
    if language == "tr":
        text = _normalize_turkish_text(text)
        if text != original_text:
            logger.info(f"TTS: normalized Turkish text: '{original_text}' -> '{text}'")

    model, tokenizer = _load_model(language)
    if model is None or tokenizer is None:
        return None

    try:
        import torch
        import scipy.io.wavfile as wavfile

        device = _get_device()

        inputs = tokenizer(text, return_tensors="pt")
        input_ids = inputs.input_ids.to(device)

        with torch.no_grad():
            outputs = model(input_ids=input_ids)

        # MMS outputs at 16kHz
        waveform = outputs.waveform.squeeze(0).cpu().numpy()
        sample_rate = 16000

        # Write to BytesIO as WAV
        buffer = io.BytesIO()
        wavfile.write(buffer, sample_rate, waveform)
        buffer.seek(0)

        wav_bytes = buffer.read()
        logger.info(f"TTS synthesized {len(wav_bytes)} bytes ({len(waveform) / sample_rate:.1f}s)")
        return wav_bytes

    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        return None
