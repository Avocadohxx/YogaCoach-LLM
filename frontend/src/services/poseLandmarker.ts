import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision';
export async function createPoseLandmarker() {
  const files = await FilesetResolver.forVisionTasks(import.meta.env.VITE_POSE_WASM || '/models/wasm');
  return PoseLandmarker.createFromOptions(files, {baseOptions:{modelAssetPath:import.meta.env.VITE_POSE_MODEL || '/models/pose_landmarker_lite.task'}, runningMode:'VIDEO', numPoses:1});
}
export const connections = PoseLandmarker.POSE_CONNECTIONS;
