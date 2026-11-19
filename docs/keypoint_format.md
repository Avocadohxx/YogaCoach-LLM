# 主链路关键点格式：COCO-WholeBody 133

当前主方案为 RTMW/DWPose 的 133 点，浏览器 MediaPipe 33 点仅保留历史兼容代码，不是当前感知入口。

- `keypoints`：133 个 `[x,y]`，单位为输入图像像素。
- `scores`：133 个原始模型分数，可超过 1，不称为 visibility 或概率。
- 关键索引：肩 5/6、肘 7/8、腕 9/10、髋 11/12、膝 13/14、踝 15/16（0 起始，左右为解剖侧）。
- `layout=COCO-WholeBody 133`，`coordinate_space=image_pixels`。
- 前端缩小图像后再发送，后端坐标对应实际收到的图像尺寸，绘制使用同一尺寸；不能乘回原视频宽高后再用于该预览。
- 质量门槛使用现有 133 点模块的原始 score 门槛，未把 MediaPipe visibility 阈值移植过来。

完整测量定义参见 [detection_rules_133.md](detection_rules_133.md)。来源：[MMPose COCO-WholeBody 定义](https://github.com/open-mmlab/mmpose/blob/main/configs/_base_/datasets/coco_wholebody.py)。
