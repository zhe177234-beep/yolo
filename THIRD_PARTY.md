# 依赖与模型来源

- Ultralytics 及 YOLO11n/YOLO11s：官方仓库 https://github.com/ultralytics/ultralytics ，AGPL-3.0 / 官方企业许可；本项目按 AGPL-3.0 开源方式使用。
- 模型由 `scripts/setup_model.py` 通过官方资产下载逻辑准备，不提交二进制权重。
- 真实推理验证中的 `bus.jpg` 来自上述官方仓库 `ultralytics/assets/bus.jpg`，运行检查时下载到临时目录；`docs/studio.jpg` 的界面截图包含该官方样图的检测画面，原始图片不单独打包。
- FastAPI、Uvicorn：BSD-3-Clause；PyTorch：BSD 类许可；OpenCV：Apache-2.0；Pillow：HPND；imageio-ffmpeg：BSD-2-Clause。具体版本及完整许可以各上游发布包为准。
- FFmpeg 包含多组件，H.264 编码器的许可见 imageio-ffmpeg 所分发二进制的上游构建说明和 https://ffmpeg.org/legal.html 。

项目源码采用 AGPL-3.0。Ultralytics 的授权选项与条款以官方 https://www.ultralytics.com/license 为准。
