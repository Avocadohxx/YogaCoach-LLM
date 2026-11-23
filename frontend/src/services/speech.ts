type RecognitionResult = { isFinal: boolean; 0: { transcript: string } };
export interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult:
    | ((event: {
        resultIndex: number;
        results: ArrayLike<RecognitionResult>;
      }) => void)
    | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
  start(): void;
  abort(): void;
}
export function recognitionConstructor(): (new () => Recognition) | undefined {
  const host = window as unknown as {
    SpeechRecognition?: new () => Recognition;
    webkitSpeechRecognition?: new () => Recognition;
  };
  return host.SpeechRecognition || host.webkitSpeechRecognition;
}
export function createSpeech(
  onText: (text: string) => void,
  status: (text: string) => void,
) {
  let enabled = false,
    speaking = false,
    epoch = 0,
    retries = 0;
  let recognition: Recognition | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stopRecognition = () => {
    clearTimeout(timer);
    if (recognition) {
      recognition.onresult =
        recognition.onerror =
        recognition.onend =
        recognition.onstart =
          null;
      recognition.abort();
      recognition = null;
    }
  };
  function listen() {
    if (!enabled || speaking) return;
    const Constructor = recognitionConstructor();
    if (!Constructor) {
      enabled = false;
      status('浏览器不支持语音识别，请使用手动阶段选择。');
      return;
    }
    const current = new Constructor();
    recognition = current;
    current.lang = 'zh-CN';
    current.continuous = true;
    current.interimResults = false;
    current.onstart = () => status('正在监听：请以“教练”开头说出口令。');
    current.onresult = (event) => {
      if (!enabled || speaking || recognition !== current) return;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (!enabled || recognition !== current) break;
        if (event.results[i].isFinal) {
          retries = 0;
          onText(event.results[i][0].transcript);
        }
      }
    };
    current.onerror = (event) => {
      if (event.error === 'no-speech' || event.error === 'aborted') return;
      enabled = false;
      stopRecognition();
      status(`语音识别已停止（${event.error}），可手动操作或重新开启。`);
    };
    current.onend = () => {
      if (recognition !== current) return;
      stopRecognition();
      if (!enabled || speaking) return;
      if (++retries > 3) {
        enabled = false;
        status('监听连续中断，请重新开启语音。');
        return;
      }
      status('监听中断，正在重新连接…');
      timer = setTimeout(listen, 700);
    };
    try {
      current.start();
    } catch {
      enabled = false;
      stopRecognition();
      status('无法开启监听，请检查浏览器与麦克风权限。');
    }
  }
  function cancel() {
    epoch++;
    const wasSpeaking = speaking;
    speaking = false;
    window.speechSynthesis?.cancel();
    if (enabled && wasSpeaking) {
      stopRecognition();
      timer = setTimeout(listen, 400);
    }
  }
  return {
    start() {
      enabled = true;
      retries = 0;
      stopRecognition();
      listen();
    },
    stop() {
      enabled = false;
      stopRecognition();
      cancel();
      status('语音已关闭。');
    },
    cancel,
    speak(text: string) {
      if (!enabled || !text) return;
      if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
        status('浏览器无法播报，建议仍显示在页面。');
        return;
      }
      cancel();
      stopRecognition();
      speaking = true;
      const token = epoch;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'zh-CN';
      utterance.voice =
        window.speechSynthesis
          .getVoices()
          .find((v) => v.lang.startsWith('zh')) || null;
      status('正在播报，暂不接收口令；播报结束后恢复监听。');
      const done = () => {
        if (token !== epoch) return;
        clearTimeout(timer);
        speaking = false;
        if (enabled) timer = setTimeout(listen, 400);
      };
      utterance.onend = done;
      utterance.onerror = () => {
        status('播报失败，建议仍显示在页面。');
        done();
      };
      // A broken speech engine must not leave listening disabled indefinitely.
      timer = setTimeout(() => {
        cancel();
        status('播报超时，恢复监听。');
      }, 30000);
      try {
        window.speechSynthesis.speak(utterance);
      } catch {
        cancel();
        status('播报失败，恢复监听。');
      }
    },
  };
}
