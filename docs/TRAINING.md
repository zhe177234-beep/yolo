# 自定义目标检测训练

以安全帽检测为例，默认 COCO 模型没有 `helmet` 类别，需要自备、标注并训练数据集。

## 数据组织

```text
dataset/
  images/train/a.jpg
  images/val/b.jpg
  labels/train/a.txt
  labels/val/b.txt
```

标签每行为 `class_id x_center y_center width height`，坐标是相对图像宽高归一化的 0–1 数值。空标签文件表示负样本。类别从 0 开始，与 YAML `names` 一致。复制 `datasets/custom.example.yaml` 为 `datasets/custom.yaml` 并改为你的绝对路径。

按摄像头、场景或拍摄日期划分训练/验证/测试数据，避免同一视频相邻帧跨集合导致数据泄漏。保留不同光照、遮挡和距离样本；确认数据使用授权。

## 训练与评估

```bash
python scripts/setup_model.py
python scripts/train.py --data datasets/custom.yaml --epochs 50 --batch 8 --device cpu
# CUDA 环境可改为 --device 0
```

CPU 更适合验证流程；正式训练优先使用合适的 GPU。小数据集先检查标签，再调整训练参数，不要单纯增加 epochs。结果在 `runs/train/custom*`，查看训练曲线、每类 precision/recall、mAP50 与 mAP50-95。使用独立测试集检验漏检、误检和真实场景延迟。

可用 `--data coco8.yaml --epochs 1 --batch 1` 验证训练管线，这仅是小样本测试，不能作为真实精度结论。

## 接入工作台

```powershell
$env:YOLO_MODEL = 'runs/train/custom/weights/best.pt'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

按实际训练输出路径填写，重启服务并选择“全部类别”。交通/行人预设只适用于标准 COCO 类别编号。工作台只接受管理员配置的本地权重，不开放用户上传 `.pt`；只加载可信来源的权重。

`--export onnx` 或 `--export torchscript` 用于导出，可能需安装 Ultralytics 提示的可选依赖。工作台已验证的运行路径是 PyTorch `.pt`，导出文件供后续边缘部署使用。
