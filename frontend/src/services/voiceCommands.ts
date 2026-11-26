import type { Phase133, Pose } from "./api";
export type VoiceCommand = Phase133 | "finish";
const commands: Record<string, VoiceCommand | "start"> = {
  教练准备: "prepare",
  教练开始: "start",
  教练放下: "arms_down_hold",
  教练结束: "finish",
  // Keep older recognized phrases working while the UI teaches the short forms.
  教练开始举臂保持: "arms_up_hold",
  教练双臂放下保持: "arms_down_hold",
  教练开始侧弯保持: "side_bend_hold",
  教练结束练习: "finish",
  教练切换动作: "finish",
};
export function parseVoiceCommand(
  text: string,
  pose: Pose,
): VoiceCommand | null {
  const parsed = commands[text.replace(/[\s，。！？、,.!?]/g, "")];
  const command: VoiceCommand | undefined =
    parsed === "start"
      ? pose === "tadasana"
        ? "arms_up_hold"
        : "side_bend_hold"
      : parsed;
  if (
    !command ||
    (command === "side_bend_hold" && pose !== "ardhakati_chakrasana")
  )
    return null;
  return command;
}
