"""LangGraph evidence -> tools -> decision -> grounded generation -> validation."""
import logging
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from backend import llm, memory
from backend.evidence import store
from backend.prompts import CAMERA_MESSAGES, CORRECTION_MESSAGES, Feedback
from backend.schemas import AnalysisResult
from backend.tools import context_for, reference_for

logger = logging.getLogger(__name__)


class State(TypedDict, total=False):
    event: AnalysisResult
    feedback: Feedback
    context: dict
    reference: dict
    selected: dict


def gate(state: State):
    event = state['event']
    if event.analysis_mode == 'synthetic_mock':
        return {'feedback': Feedback(text='模拟事件不用于真实动作纠正。', reason='synthetic_event')}
    if not store.trusted(event):
        return {'feedback': Feedback(text='分析证据已过期或未经服务器确认。', reason='untrusted_or_expired')}
    return {}


def retrieve(state: State):
    event = state['event']
    try:
        return {'reference': reference_for(event.pose_id), 'context': context_for(event.session_id, event.pose_id)}
    except (ValueError, OSError):
        return {'feedback': Feedback(text='练习会话或参考资料不可用。', reason='tools_unavailable')}


def decide(state: State):
    event = state['event']
    tools = ['analysis_snapshot', 'reference_for', 'context_for']
    if event.analysis_mode == 'reviewed_rules_133' and event.feedback_allowed:
        candidates = [d for d in event.deviations if (d.type, getattr(d, 'target', None)) in CORRECTION_MESSAGES
                      and not store.correction_spoken(event.session_id, d.event_id)]
        if not candidates:
            return {'feedback': Feedback(reason='episode_already_reported', tools_used=tools)}
        prior=state['context'].get('prior_focus',[])
        candidates.sort(key=lambda d: not any(x['type']==d.type and x['side']==d.side for x in prior))
        return {'selected': candidates[0].model_dump()}
    if event.tracking_quality == 'good':
        return {'feedback': Feedback(text='当前测量未触发新的持续偏差提醒。' if event.analysis_mode == 'reviewed_rules_133' else '已获取姿态测量；当前阶段或规则尚不能提供纠错。', reason='no_confirmed_deviation' if event.analysis_mode == 'reviewed_rules_133' else 'uncalibrated', tools_used=tools)}
    if not store.reserve(event.session_id, 'camera_hint'):
        return {'feedback': Feedback(reason='cooldown', tools_used=tools)}
    return {}


def compose(state: State):
    preference = state['context']['preferences'].get('feedback_length')
    preference = preference if preference in ('short', 'normal', 'long') else None
    selected = state.get('selected')
    messages = CORRECTION_MESSAGES[(selected['type'], selected['target'])] if selected else CAMERA_MESSAGES
    message_id, mode, reason = ('short' if preference == 'short' else 'full'), 'template', 'llm_unavailable'
    prior_focus = state['context'].get('prior_focus', [])
    continue_focus = bool(selected and any(
        item['type'] == selected['type'] and item['side'] == selected['side']
        for item in prior_focus
    ))
    prefix = '这次继续留意上次关注的位置。' if continue_focus else ''
    try:
        if selected:
            try:
                evidence = _correction_evidence(selected, state['event'], state['reference'])
                suggestion = llm.generate_correction(evidence)
                _validate_suggestion(suggestion, selected)
            except Exception:
                logger.info('LLM correction unavailable or failed validation; using grounded rule template')
                suggestion = None
            if suggestion is None:
                fallback = _fallback_correction(selected)
                if fallback is None:
                    return {'feedback': Feedback(reason='llm_unavailable_no_safe_template')}
                return {'feedback': Feedback(
                    should_speak=True, feedback_type='correction', text=prefix + fallback,
                    mode='template', reason='llm_unavailable_or_invalid',
                    event_id=selected['event_id'], target=selected['target'],
                    grounded_event_type=selected['type'],
                    tools_used=['analysis_snapshot', 'reference_for', 'context_for'],
                )}
            return {'feedback': Feedback(
                should_speak=True, feedback_type='correction', text=prefix + suggestion.text,
                mode='llm', reason='confirmed_rule_deviation', event_id=selected['event_id'],
                target=selected['target'], grounded_event_type=selected['type'],
                tools_used=['analysis_snapshot', 'reference_for', 'context_for'],
            )}
        message_id = llm.select_message(preference)
        # Validate even an injected/test provider's return before indexing templates.
        if message_id not in messages:
            raise ValueError('invalid_selection')
        mode, reason = 'llm', 'camera_quality'
    except Exception:
        # Provider errors can contain credentials or response bodies: do not log them.
        message_id = 'short' if preference == 'short' else 'full'
        logger.info('LLM selector unavailable; using camera template')
    text=messages[message_id]
    text = prefix + text
    return {'feedback': Feedback(should_speak=True, feedback_type='correction' if selected else 'camera_hint',
        text=text, mode=mode, reason=reason,
        event_id=selected['event_id'] if selected else None, target=selected['target'] if selected else None,
        grounded_event_type=selected['type'] if selected else None,
        tools_used=['analysis_snapshot', 'reference_for', 'context_for'])}


def _correction_evidence(selected: dict, event: AnalysisResult, reference: dict) -> dict:
    """Build grounded evidence with one correction target and contextual measures."""
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parents[1]
    ruleset = None
    rule_file = reference.get('rules_file')
    if not rule_file:
        raise ValueError('reviewed_ruleset_missing')
    rule_path = Path(rule_file)
    if not rule_path.is_absolute():
        rule_path = root / 'knowledge' / rule_path
    try:
        candidate = json.loads(rule_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('reviewed_ruleset_missing') from exc
    ruleset = candidate if any(
        item.get('rule_id') == selected.get('rule_id') for item in candidate.get('rules', [])
    ) else None
    if ruleset is None:
        raise ValueError('reviewed_ruleset_missing')
    if not ruleset.get('reviewed'):
        raise ValueError('reviewed_ruleset_required')
    rule = next((item for item in ruleset.get('rules', [])
                 if item.get('rule_id') == selected.get('rule_id')), None)
    if (rule is None or not ruleset.get('reviewed') or not rule.get('enabled')
            or rule.get('mode') != 'candidate'):
        raise ValueError('confirmed_rule_missing_from_reference')
    value = selected.get('observed_value')
    lo, hi = selected.get('reference_range') or [None, None]
    if value is None or (lo is None and hi is None):
        raise ValueError('incomplete_numeric_evidence')
    unit = rule.get('unit')
    if not unit:
        raise ValueError('reference_unit_missing')
    configured_rules = {item['rule_id']: item for item in ruleset.get('rules', [])}
    evaluated_rules = {
        item.get('rule_id'): item
        for item in (event.rule_evaluation or {}).get('rule_results', [])
        if isinstance(item, dict) and isinstance(item.get('rule_id'), str)
    }
    # Include only finite, server-validated measurements. Monitor-only values are
    # explicitly marked as context so they cannot become independent corrections.
    contextual_measurements = []
    for observation in event.observations:
        rule = next((item for item in configured_rules.values()
                     if item.get('feature_name') == observation.name), None)
        evaluated = evaluated_rules.get(rule.get('rule_id')) if rule else None
        contextual_measurements.append({
            'feature_name': observation.name,
            'value': observation.value if observation.valid else None,
            'unit': observation.unit,
            'valid': observation.valid,
            'invalid_reason': observation.reason,
            'rule_mode': rule.get('mode') if rule else 'measurement_only',
            'rule_enabled': rule.get('enabled', False) if rule else False,
            'rule_transform': rule.get('transform') if rule else None,
            'rule_status': evaluated.get('status') if evaluated else 'not_evaluated',
            'comparison_value': evaluated.get('comparison_value') if evaluated else None,
            'reference_range': rule.get('reference_range') if rule else None,
            'use_for_correction': bool(rule and rule.get('enabled')
                                       and rule.get('mode') == 'candidate'
                                       and evaluated and evaluated.get('status') == 'deviation'),
        })

    return {
        'pose': event.pose_id,
        'confirmed_deviation': {
            'rule_id': selected['rule_id'],
            'target': selected['target'],
            'event_type': selected['type'],
            'feature_name': selected['feature_name'],
            'observed_value': value,
            'unit': unit,
            'reference_range': [lo, hi],
            'duration_ms': selected['duration_ms'],
        },
        # Keep top-level fields for compatibility with existing provider prompts.
        'target': selected['target'],
        'event_type': selected['type'],
        'feature_name': selected['feature_name'],
        'observed_value': value,
        'unit': unit,
        'reference_range': [lo, hi],
        'phase': (event.rule_evaluation or {}).get('phase'),
        'duration_ms': selected['duration_ms'],
        'minimum_keypoint_score': selected.get('min_keypoint_score'),
        'rule_provenance': {
            'rule_version': ruleset.get('version'),
            'rules_reviewed': (event.rule_evaluation or {}).get('reviewed'),
            'review_record': ruleset.get('review_record'),
            'execution_mode': 'reviewed_rules' if ruleset.get('reviewed') else 'exploratory_preview',
            'phase_reviewed': (event.rule_evaluation or {}).get('phase_reviewed'),
            'phase_source': (event.rule_evaluation or {}).get('phase_source'),
            'camera_view_verified': (event.rule_evaluation or {}).get('camera_view_verified'),
            'scope': (event.rule_evaluation or {}).get('scope'),
        },
        'context_measurements': contextual_measurements,
        'safety_constraints': [
            '不要诊断疾病或声称疼痛',
            '不要求强行达到角度或锁死关节',
            '只能针对 confirmed_deviation.target 给出纠错；其他观测值只能作为背景',
            'rule_mode=monitor_only 或 use_for_correction=false 的测量不得称为偏差或据此提出纠正',
            '保留规则审核、阶段确认和二维测量的限制，不推断全身姿态',
            '感到不适时暂停练习',
        ],
    }


def _validate_suggestion(suggestion, selected: dict) -> None:
    """Reject unsupported target/type and unsafe or unbounded model replies."""
    text = suggestion.text.strip()
    forbidden = ('诊断', '治疗', '治愈', '必须锁死', '强行达到', '保证改善')
    if (not text or suggestion.target != selected['target']
            or suggestion.grounded_event_type != selected['type']
            or any(token in text for token in forbidden)):
        raise ValueError('llm_suggestion_failed_validation')


def _fallback_correction(selected: dict) -> str | None:
    messages = CORRECTION_MESSAGES.get((selected.get('type'), selected.get('target')))
    return messages.get('full') if messages else None


def validate(state: State):
    event, reply = state['event'], state['feedback']
    if reply.should_speak:
        try:
            session = memory.get_session(event.session_id)
            if not store.trusted(event, reply.event_id if reply.feedback_type == 'correction' else None) or session is None or session['ended_at'] is not None:
                return {'feedback': Feedback(reason='evidence_withdrawn')}
            if reply.feedback_type == 'correction':
                if not store.claim_correction(event.session_id, reply.event_id):
                    return {'feedback': Feedback(reason='correction_cooldown_or_duplicate')}
            # Logs represent returned hints, not proof of speech playback.
            memory.log_feedback(event.session_id, reply.grounded_event_type or 'camera_hint', reply.text)
        except ValueError:
            return {'feedback': Feedback(reason='session_unavailable')}
    return {}


def build_graph():
    graph = StateGraph(State)
    for name, node in [('gate', gate), ('tools', retrieve), ('decide', decide), ('compose', compose), ('validate', validate)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'gate')
    for source, next_node in [('gate', 'tools'), ('tools', 'decide'), ('decide', 'compose')]:
        graph.add_conditional_edges(source, lambda state, dest=next_node: 'validate' if 'feedback' in state else dest)
    graph.add_edge('compose', 'validate')
    graph.add_edge('validate', END)
    return graph.compile()


workflow = build_graph()


def feedback_for(event: AnalysisResult) -> Feedback:
    return workflow.invoke({'event': event})['feedback']
