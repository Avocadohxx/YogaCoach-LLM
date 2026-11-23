import { useEffect, useRef, useState } from 'react';
import { createSpeech } from '../services/speech';
import {
  parseVoiceCommand,
  type VoiceCommand,
} from '../services/voiceCommands';
import type { Pose } from '../services/api';
export function useVoiceCoach(
  active: boolean,
  busy: boolean,
  pose: Pose,
  execute: (command: VoiceCommand) => void,
) {
  const [status, setStatus] = useState('语音已关闭。');
  const [heard, setHeard] = useState('');
  const callbacks = useRef({ active, busy, pose, execute });
  callbacks.current = { active, busy, pose, execute };
  const service = useRef<ReturnType<typeof createSpeech> | null>(null);
  useEffect(() => {
    const speech = createSpeech((text) => {
      const current = callbacks.current;
      if (!current.active || current.busy) return;
      setHeard(text);
      const command = parseVoiceCommand(text, current.pose);
      if (command) current.execute(command);
      else setStatus('未匹配口令，阶段未改变。请使用下方示例。');
    }, setStatus);
    service.current = speech;
    return () => {
      speech.stop();
      service.current = null;
    };
  }, []);
  useEffect(() => {
    if (!active) {
      service.current?.stop();
      setHeard('');
    }
  }, [active]);
  return {
    status,
    heard,
    start: () => {
      if (active && !busy) service.current?.start();
    },
    stop: () => service.current?.stop(),
    cancel: () => service.current?.cancel(),
    speak: (text: string) => service.current?.speak(text),
  };
}
