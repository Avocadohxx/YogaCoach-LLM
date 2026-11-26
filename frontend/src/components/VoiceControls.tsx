type Props = {
  disabled: boolean;
  status: string;
  heard: string;
  start: () => void;
  stop: () => void;
  cancel: () => void;
};
export default function VoiceControls(props: Props) {
  return (
    <section className="card voice-panel" aria-label="语音控制">
      <div>
        <h2>语音控制</h2>
        <p className="voice-description">
          开启后在本次练习中持续监听，不保存录音。浏览器识别服务可能将音频发送到外部服务，需联网；播报期间暂不接收口令。
        </p>
      </div>
      <div className="voice-actions">
        <button disabled={props.disabled} onClick={props.start}>
          开启语音
        </button>{" "}
        <button onClick={props.stop}>关闭语音</button>{" "}
        <button onClick={props.cancel}>立即停止播报</button>
      </div>
      <p className="voice-status" role="status">
        {props.status}
      </p>
      {props.heard && <p className="voice-heard">听到：{props.heard}</p>}
      <p className="voice-commands">
        口令：教练，准备 / 开始 / 放下 / 结束。每条均以“教练”开头。
      </p>
    </section>
  );
}
