"""Optional chat-completions provider for grounded, structured coaching."""
import json
import os
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal
from backend.prompts import COACHING_SYSTEM_PROMPT, SELECTION_PROMPT


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: Literal["full", "short"]


class CoachingSuggestion(BaseModel):
    """Strict response schema for suggestions grounded in one confirmed rule."""
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=8, max_length=500)
    target: str = Field(min_length=1, max_length=80)
    grounded_event_type: str = Field(min_length=1, max_length=80)


def _select(preference: str | None, prompt: str) -> str:
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not key or key == "replace_me" or not base or not model or model == "replace_me":
        raise ValueError("llm_not_configured")
    # Only an allowlisted preference is sent; no raw keypoints/history/identifiers.
    with httpx.Client(timeout=httpx.Timeout(3.0), follow_redirects=False) as client:
        response = client.post(base + "/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
            "model": model, "temperature": 0, "max_tokens": 40,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": json.dumps({"feedback_length": preference})}],
        })
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return Selection.model_validate_json(content).message_id


def generate_correction(evidence: dict) -> CoachingSuggestion:
    """Ask the provider to phrase one confirmed deviation as safe advice.

    Only the compact numeric/rule summary is sent; no image, raw landmarks,
    session identifiers, or memory context leaves the local backend.
    """
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not key or key == "replace_me" or not base or not model or model == "replace_me":
        raise ValueError("llm_not_configured")
    with httpx.Client(timeout=httpx.Timeout(8.0), follow_redirects=False) as client:
        response = client.post(base + "/chat/completions", headers={
            "Authorization": f"Bearer {key}",
        }, json={
            "model": model,
            "temperature": 0.2,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": COACHING_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, allow_nan=False)},
            ],
        })
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    return CoachingSuggestion.model_validate_json(content)


def select_message(preference: str | None) -> str:
    return _select(preference, SELECTION_PROMPT)


def select_correction(preference: str | None) -> str:
    return _select(preference, SELECTION_PROMPT)
