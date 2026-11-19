"""LangGraph evidence -> tools -> decision -> bounded generation -> validation.

Reviewed 133-point rules may produce grounded correction templates. Other
inputs remain measurement-only. Tools are deterministic graph-node calls.
"""
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
    try:
        message_id = (llm.select_correction if selected else llm.select_message)(preference)
        # Validate even an injected/test provider's return before indexing templates.
        if message_id not in messages:
            raise ValueError('invalid_selection')
        mode, reason = 'llm', 'confirmed_rule_deviation' if selected else 'camera_quality'
    except Exception:
        # Provider errors can contain credentials or response bodies: do not log them.
        message_id = 'short' if preference == 'short' else 'full'
        logger.info('LLM selector unavailable; using camera template')
    return {'feedback': Feedback(should_speak=True, feedback_type='correction' if selected else 'camera_hint',
        text=messages[message_id], mode=mode, reason=reason,
        event_id=selected['event_id'] if selected else None, target=selected['target'] if selected else None,
        grounded_event_type=selected['type'] if selected else None,
        tools_used=['analysis_snapshot', 'reference_for', 'context_for'])}


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
