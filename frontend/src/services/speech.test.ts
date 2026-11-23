// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { createSpeech, type Recognition } from './speech';
import { parseVoiceCommand } from './voiceCommands';
let instances: Recognition[] = [];
class FakeRecognition {
  lang = '';
  continuous = false;
  interimResults = false;
  onresult: Recognition['onresult'] = null;
  onerror: Recognition['onerror'] = null;
  onend: Recognition['onend'] = null;
  onstart: Recognition['onstart'] = null;
  start = vi.fn();
  abort = vi.fn();
  constructor() {
    instances.push(this);
  }
}
function setup() {
  vi.useFakeTimers();
  instances = [];
  vi.stubGlobal('SpeechRecognition', FakeRecognition);
  vi.stubGlobal(
    'SpeechSynthesisUtterance',
    class {
      text: string;
      constructor(text: string) {
        this.text = text;
      }
    },
  );
  const synth = { speak: vi.fn(), cancel: vi.fn(), getVoices: () => [] };
  vi.stubGlobal('speechSynthesis', synth);
  const text = vi.fn(),
    status = vi.fn();
  const service = createSpeech(text, status);
  return { service, text, status, synth };
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it('匹配明确口令，拒绝否定、闲聊和错误动作阶段', () => {
  expect(parseVoiceCommand('教练，开始举臂保持。', 'tadasana')).toBe(
    'arms_up_hold',
  );
  for (const text of [
    '教练不要开始举臂保持',
    '开始举臂保持',
    '教练下一阶段',
    '教练开始侧弯保持',
  ])
    expect(parseVoiceCommand(text, 'tadasana')).toBeNull();
  expect(parseVoiceCommand('教练开始侧弯保持', 'ardhakati_chakrasana')).toBe(
    'side_bend_hold',
  );
});
it('只发送最终识别结果，播报期间关闭识别，结束恢复', () => {
  const t = setup();
  t.service.start();
  const r = instances[0];
  r.onresult!({
    resultIndex: 0,
    results: [
      { isFinal: false, 0: { transcript: '中间结果' } },
      { isFinal: true, 0: { transcript: '教练准备' } },
    ],
  });
  expect(t.text).toHaveBeenCalledExactlyOnceWith('教练准备');
  t.service.speak('有效建议');
  expect(r.abort).toHaveBeenCalled();
  expect(r.onresult).toBeNull();
  t.synth.speak.mock.calls[0][0].onend();
  vi.advanceTimersByTime(400);
  expect(instances.length).toBe(2);
  t.service.stop();
});
it('取消旧播报后，迟到结束回调不能恢复监听', () => {
  const t = setup();
  t.service.start();
  t.service.speak('建议');
  const end = t.synth.speak.mock.calls[0][0].onend;
  t.service.stop();
  end();
  vi.runAllTimers();
  expect(instances.length).toBe(1);
  expect(t.synth.cancel).toHaveBeenCalled();
});
it('拒绝权限后不反复重启', () => {
  const t = setup();
  t.service.start();
  instances[0].onerror!({ error: 'not-allowed' });
  vi.runAllTimers();
  expect(instances.length).toBe(1);
  expect(instances[0].onend).toBeNull();
});
