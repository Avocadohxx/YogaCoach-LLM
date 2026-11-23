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
    <section className="card" aria-label="语音控制">
      <h2>语音陪练</h2>
      <p>
        开启后在本次练习中持续监听，不保存录音。浏览器识别服务可能将音频发送到外部服务，需联网；播报期间暂不接收口令。
      </p>
      <button disabled={props.disabled} onClick={props.start}>
        开启语音
      </button>{" "}
      <button onClick={props.stop}>关闭语音</button>{" "}
      <button onClick={props.cancel}>立即停止播报</button>
      <p role="status">{props.status}</p>
      {props.heard && <p>听到：{props.heard}</p>}
      <p>
        口令：教练，准备 / 开始举臂保持 / 双臂放下保持 / 切换动作 / 开始侧弯保持
        / 结束练习。每条均以“教练”开头。
      </p>
    </section>
  );
}
