"""Thin wrapper around any OpenAI-compatible chat endpoint.

Small/free models are unreliable at producing clean JSON, so every structured
call goes through: reasoning-tag stripping -> tolerant JSON extraction ->
pydantic validation -> one self-repair round-trip.
"""

import json
import logging
import re
import threading
import time
from typing import Annotated, Any, TypeVar
from urllib.parse import urlparse

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, BeforeValidator, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


_client: OpenAI | None = None
_client_lock = threading.Lock()
# Some providers reject response_format; remember that after the first 400.
_json_mode_supported = True


def is_configured() -> bool:
    return bool(settings.llm_api_key)


def provider_host() -> str:
    return (urlparse(settings.llm_base_url).hostname or "").lower()


def model_chain() -> list[str]:
    """Main model followed by fallbacks, without duplicates."""
    fallbacks = list(settings.llm_fallback_models)
    if not fallbacks and provider_host().endswith("openrouter.ai"):
        fallbacks = ["openrouter/free"]
    return list(dict.fromkeys(m for m in [settings.llm_model, *fallbacks] if m))


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(
                    api_key=settings.llm_api_key or "missing",
                    base_url=settings.llm_base_url,
                    timeout=settings.llm_timeout,
                    max_retries=0,
                )
    return _client


_TRANSIENT = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)

# model -> reason it can't be used; model -> unix time until which it is skipped
_missing_models: dict[str, str] = {}
_cooldown_until: dict[str, float] = {}
_COOLDOWN_SECONDS = 300
_health_lock = threading.Lock()


def check_models() -> dict:
    """Ask the provider which models exist and flag configured ones that don't.

    Runs once at startup; a provider that can't list models is simply not checked."""
    status = {"checked": False, "missing": []}
    if not is_configured():
        return status
    try:
        available = {m.id for m in _get_client().models.list()}
    except Exception as exc:
        log.info("Could not list models from %s: %s", provider_host(), exc)
        return status
    status["checked"] = True
    for model in model_chain():
        if model not in available:
            with _health_lock:
                _missing_models[model] = "not offered by the provider"
            status["missing"].append(model)
    if settings.llm_model in status["missing"]:
        log.error(
            "LLM_MODEL %r does not exist on %s. Set LLM_MODEL to a valid model id; using fallbacks %s meanwhile.",
            settings.llm_model, provider_host(), model_chain()[1:] or "none",
        )
    return status


def model_status() -> dict:
    with _health_lock:
        missing = dict(_missing_models)
        cooling = {m: round(t - time.time()) for m, t in _cooldown_until.items() if t > time.time()}
    return {
        "provider": provider_host(),
        "model": settings.llm_model,
        "fallback_models": model_chain()[1:],
        "model_available": settings.llm_model not in missing,
        "unavailable_models": missing,
        "cooling_down": cooling,
    }


def _usable(model: str) -> bool:
    with _health_lock:
        return model not in _missing_models and _cooldown_until.get(model, 0) <= time.time()


@retry(
    retry=retry_if_exception_type(_TRANSIENT),
    stop=stop_after_attempt(max(1, settings.llm_max_retries)),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def _create(**kwargs: Any) -> str:
    response = _get_client().chat.completions.create(**kwargs)
    if not response.choices:
        raise LLMError("LLM returned no choices")
    return response.choices[0].message.content or ""


def _is_model_error(exc: APIStatusError) -> bool:
    text = str(exc).lower()
    return isinstance(exc, NotFoundError) or any(
        needle in text for needle in ("not a valid model", "model not found", "no endpoints found", "does not exist", "unknown model")
    )


def _call_model(model: str, kwargs: dict[str, Any]) -> str:
    global _json_mode_supported
    try:
        return _create(model=model, **kwargs)
    except BadRequestError as exc:
        if "response_format" in kwargs and not _is_model_error(exc):
            log.info("Provider rejected response_format, falling back to prompt-only JSON")
            _json_mode_supported = False
            kwargs.pop("response_format")
            return _create(model=model, **kwargs)
        raise


def complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    json_mode: bool = False,
) -> str:
    """Run a chat completion and return the assistant text (reasoning removed).

    Tries the main model, then each fallback model. A model the provider says
    doesn't exist is skipped from then on; one that keeps failing is paused
    for a few minutes so later calls go straight to a working model."""
    if not is_configured():
        raise LLMError("LLM_API_KEY is not configured")

    if settings.base_prompt and messages and messages[0]["role"] == "system":
        messages = [
            {"role": "system", "content": f"{settings.base_prompt}\n\n{messages[0]['content']}"},
            *messages[1:],
        ]

    kwargs: dict[str, Any] = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode and _json_mode_supported:
        kwargs["response_format"] = {"type": "json_object"}

    chain = model_chain()
    candidates = [m for m in chain if _usable(m)] or chain  # never give up without trying something
    errors: list[str] = []
    for model in candidates:
        try:
            text = _call_model(model, dict(kwargs))
            with _health_lock:
                _cooldown_until.pop(model, None)
            return strip_reasoning(text)
        except APIStatusError as exc:
            if _is_model_error(exc):
                with _health_lock:
                    _missing_models[model] = f"HTTP {exc.status_code}: model not available"
            elif exc.status_code >= 500 or exc.status_code == 429:
                with _health_lock:
                    _cooldown_until[model] = time.time() + _COOLDOWN_SECONDS
            elif exc.status_code in (401, 403):
                raise LLMError(f"The LLM provider rejected the API key (HTTP {exc.status_code}). Check LLM_API_KEY.") from exc
            else:
                raise LLMError(f"LLM request rejected by {model}: {exc}") from exc
            errors.append(f"{model}: HTTP {exc.status_code}")
            log.warning("Model %s failed (%s), trying the next one", model, exc.status_code)
        except (APIConnectionError, APITimeoutError) as exc:
            with _health_lock:
                _cooldown_until[model] = time.time() + _COOLDOWN_SECONDS
            errors.append(f"{model}: {type(exc).__name__}")

    hint = ""
    if settings.llm_model in _missing_models:
        hint = f" LLM_MODEL '{settings.llm_model}' does not exist on {provider_host()}; set a valid model id."
    raise LLMError(f"No model could answer ({'; '.join(errors)}).{hint}")


_REASONING_BLOCKS = re.compile(
    r"<(think|thinking|reasoning|reflection)>.*?</\1>", re.DOTALL | re.IGNORECASE
)


def strip_reasoning(text: str) -> str:
    text = _REASONING_BLOCKS.sub("", text or "")
    # Unterminated reasoning block: keep whatever follows the last closing tag
    for tag in ("</think>", "</thinking>"):
        if tag in text:
            text = text.rsplit(tag, 1)[1]
    return text.strip()


def extract_json(text: str) -> Any:
    """Best-effort extraction of the JSON object embedded in model output."""
    if not text:
        return None
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    # Outermost {...} span first, raw then with trailing commas removed
    first, last = candidate.find("{"), candidate.rfind("}")
    spans = [candidate]
    if 0 <= first < last:
        spans.append(candidate[first:last + 1])
    for span in spans:
        for attempt in (span, re.sub(r",\s*([}\]])", r"\1", span)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
    # Last resort: first decodable object anywhere in the text
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\{\[]", candidate):
        try:
            value, _ = decoder.raw_decode(candidate[match.start():])
            if isinstance(value, (dict, list)):
                return value
        except json.JSONDecodeError:
            continue
    return None


def chat_json(
    system: str,
    user: str,
    schema: type[T],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1800,
    attempts: int = 2,
) -> T:
    """Ask for JSON matching `schema`; retries once with the validation error."""
    example = json.dumps(_schema_example(schema), indent=1)
    messages = [
        {
            "role": "system",
            "content": (
                f"{system}\n\nRespond with ONE valid JSON object and nothing else "
                f"(no markdown, no commentary). Use exactly this shape:\n{example}"
            ),
        },
        {"role": "user", "content": user},
    ]
    last_error = "no response"
    for _ in range(max(1, attempts)):
        text = complete(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
        data = extract_json(text)
        if data is None:
            last_error = "the response did not contain a JSON object"
        else:
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
            try:
                return schema.model_validate(data)
            except ValidationError as exc:
                last_error = _short_validation_error(exc)
        messages = [
            *messages,
            {"role": "assistant", "content": text[:4000]},
            {
                "role": "user",
                "content": f"That was not valid: {last_error}. Reply again with ONLY the corrected JSON object.",
            },
        ]
    raise LLMError(f"Could not get valid JSON from the model: {last_error}")


def chat_text(system: str, messages: list[dict[str, str]], **kwargs: Any) -> str:
    return complete([{"role": "system", "content": system}, *messages], **kwargs)


def _short_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"]) or "root"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def _schema_example(schema: type[BaseModel]) -> Any:
    example = getattr(schema, "example", None)
    if callable(example):
        return example()
    return {name: "..." for name in schema.model_fields}


# ---------- shared field types for agent outputs ----------


def _coerce_score(value: Any) -> float:
    """Accept 7, "7", "7/10", "70%", 0.7 and clamp to 0..10."""
    if value is None or value == "":
        raise ValueError("score is required")
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if not match:
            raise ValueError(f"not a number: {value!r}")
        number = float(match.group())
        if "%" in value:
            number /= 10
    else:
        number = float(value)
    if 0 < number <= 1 and not float(number).is_integer():
        number *= 10  # model answered on a 0..1 scale
    return round(min(10.0, max(0.0, number)), 1)


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip(" -•\t") for v in re.split(r"\n|;", value) if v.strip(" -•\t")]
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                item = next((v for v in item.values() if isinstance(v, str)), "")
            if str(item).strip():
                out.append(str(item).strip())
        return out
    return [str(value)]


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value).strip()


Score = Annotated[float, BeforeValidator(_coerce_score)]
StrList = Annotated[list[str], BeforeValidator(_coerce_str_list)]
Text = Annotated[str, BeforeValidator(_coerce_str)]


def objects_from(key: str):
    """Before-validator turning ["a", "b"] into [{key: "a"}, {key: "b"}]."""

    def _coerce(value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, dict)):
            value = [value]
        if isinstance(value, list):
            return [{key: item} if isinstance(item, str) else item for item in value if item]
        return value

    return BeforeValidator(_coerce)
