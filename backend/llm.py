"""Optional chat-completions provider for grounded, structured coaching."""
import atexit
import json
import os
from threading import Lock
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal
from backend.prompts import SELECTION_PROMPT


_client_lock = Lock()
_clients: dict[tuple[object, str], httpx.Client] = {}


def _client_for(base: str) -> httpx.Client:
    """Keep provider connections pooled for reuse throughout the backend process."""
    factory = httpx.Client
    cache_key = (factory, base)
    with _client_lock:
        client = _clients.get(cache_key)
        if client is None or client.is_closed:
            client = factory(
                follow_redirects=False,
                limits=httpx.Limits(keepalive_expiry=None),
            )
            _clients[cache_key] = client
        return client


def _close_clients() -> None:
    with _client_lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        client.close()


atexit.register(_close_clients)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: Literal["full", "short"]


class CoachingSuggestion(BaseModel):
    """Strict response schema for suggestions grounded in one confirmed rule."""
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=8, max_length=500)
    target: str = Field(min_length=1, max_length=80)
    grounded_event_type: str = Field(min_length=1, max_length=80)


class ProgressSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    trend: Literal["improving", "maintaining", "needs_attention", "insufficient_data"]
    encouragement: str = Field(min_length=4, max_length=500)
    summary: str = Field(min_length=8, max_length=1200)
    suggestions: list[str] = Field(min_length=1, max_length=3)

    @classmethod
    def model_validate_json(cls, json_data, *args, **kwargs):
        """Normalize common provider JSON variations before strict validation."""
        data = json.loads(json_data)
        if isinstance(data, dict):
            trend_aliases = {
                "进步": "improving", "有所进步": "improving", "improved": "improving",
                "保持": "maintaining", "稳定": "maintaining", "stable": "maintaining",
                "需加强": "needs_attention", "需要关注": "needs_attention",
                "保持练习": "needs_attention", "数据不足": "insufficient_data",
            }
            if isinstance(data.get("trend"), str):
                data["trend"] = trend_aliases.get(data["trend"], data["trend"])
            if isinstance(data.get("suggestions"), str):
                data["suggestions"] = [data["suggestions"]]
        return cls.model_validate(data, *args, **kwargs)


def configured() -> bool:
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    return bool(key and key != "replace_me" and base and model and model != "replace_me")


def _select(preference: str | None, prompt: str) -> str:
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not key or key == "replace_me" or not base or not model or model == "replace_me":
        raise ValueError("llm_not_configured")
    # Only an allowlisted preference is sent; no raw keypoints/history/identifiers.
    client = _client_for(base)
    response = client.post(base + "/chat/completions", timeout=3.0,
        headers={"Authorization": f"Bearer {key}"}, json={
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
    preference = "short" if evidence.get("feedback_length") == "short" else "normal"
    max_tokens = {"short": 128, "normal": 192}[preference]
    # Send only the confirmed rule and the provenance needed to keep the
    # response grounded. Full measurements and duplicate fields add latency.
    provenance = evidence.get("rule_provenance") or {}
    compact = {
        "feedback_length": preference,
        "pose": evidence.get("pose"),
        "confirmed_deviation": evidence.get("confirmed_deviation"),
        "target": evidence.get("target"),
        "event_type": evidence.get("event_type"),
        "observed_value": evidence.get("observed_value"),
        "unit": evidence.get("unit"),
        "reference_range": evidence.get("reference_range"),
        "phase": evidence.get("phase"),
        "duration_ms": evidence.get("duration_ms"),
        "rule_provenance": {
            name: provenance.get(name)
            for name in (
                "rules_reviewed", "review_record", "execution_mode",
                "phase_reviewed", "phase_source", "camera_view_verified",
            )
            if name in provenance
        },
    }
    prompt = (
        "你是谨慎、温和的瑜伽教练。只根据 confirmed_deviation 给出一句建议，"
        "只纠正其中 target；其余字段仅作背景，monitor-only、未启用或无效测量不能称为偏差。"
        "这是二维观测，不推断三维或全身姿态；bend_direction 是画面方向，不鼓励加深侧弯。"
        "遵守 rule_provenance；课程演示启用不等于专业审核通过。不得诊断、推测疼痛、夸大证据、"
        "强迫角度或锁关节；不适时提示暂停。按 feedback_length 控制建议长度：short 不超过45字，"
        "normal 不超过70字。只返回 JSON，字段为 text、target、"
        "grounded_event_type；target 和 grounded_event_type 必须逐字复制 confirmed_deviation 中的值。"
    )
    client = _client_for(base)
    response = client.post(base + "/chat/completions", timeout=8.0, headers={
        "Authorization": f"Bearer {key}",
    }, json={
        "model": model,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(compact, ensure_ascii=False, allow_nan=False)},
        ],
    })
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return CoachingSuggestion.model_validate_json(content)


def generate_progress_summary(evidence: dict) -> ProgressSummary:
    """Summarize stored practice trends; input contains aggregate DB facts only."""
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not key or key == "replace_me" or not base or not model or model == "replace_me":
        raise ValueError("llm_not_configured")
    system = """你是温和、谨慎的瑜伽练习总结助手。输入是数据库中已保存的练习记录、服务器确认的规则偏差、提示日志和用户明确设置的偏好。按同一规则和目标的每次训练数据比较 deviation_from_range：数值减小可描述为该规则偏差减小，不可据此保证整体动作进步；数值持续或增加时，给予鼓励并提出一到三条安全、具体的下一步建议。数据不足时必须明确说无法判断趋势。不要把没有记录的训练说成正确，不要把 monitor-only 项说成错误，不做医疗判断；对规则版本不同的数据不要直接比较。尊重 preferences。

必须直接返回且只返回一个 JSON 对象，不要输出 Markdown、代码围栏、解释或其他字段。格式示例：{"trend":"improving","encouragement":"练习有进步，继续保持。","summary":"相同规则下偏离值呈下降趋势。","suggestions":["保持舒适的练习幅度。"]}。trend 只能是 improving、maintaining、needs_attention、insufficient_data 之一；encouragement 和 summary 是字符串；suggestions 必须是一到三条建议组成的字符串数组。"""
    client = _client_for(base)
    response = client.post(base + "/chat/completions", timeout=20.0, headers={
        "Authorization": f"Bearer {key}",
    }, json={
        "model": model, "temperature": 0.1, "max_tokens": 1400,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, allow_nan=False)},
        ],
    })
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return ProgressSummary.model_validate_json(content)


def select_message(preference: str | None) -> str:
    return _select(preference, SELECTION_PROMPT)


def select_correction(preference: str | None) -> str:
    return _select(preference, SELECTION_PROMPT)
