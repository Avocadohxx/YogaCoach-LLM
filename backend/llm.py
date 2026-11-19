"""Optional chat-completions-compatible selector; never emits free-form coaching."""
import json
import os
import httpx
from pydantic import BaseModel, ConfigDict
from typing import Literal
from backend.prompts import SELECTION_PROMPT, CORRECTION_SELECTION_PROMPT


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: Literal["full", "short"]


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


def select_message(preference: str | None) -> str:
    return _select(preference, SELECTION_PROMPT)


def select_correction(preference: str | None) -> str:
    return _select(preference, CORRECTION_SELECTION_PROMPT)
