import { cp, mkdir } from 'node:fs/promises';
const source = new URL('../node_modules/@mediapipe/tasks-vision/wasm/', import.meta.url);
const target = new URL('../public/models/wasm/', import.meta.url);
await mkdir(target, {recursive:true});
await cp(source,target,{recursive:true});
console.log('已复制与安装版本一致的 WASM 文件。请另外放置 pose_landmarker_lite.task。');
