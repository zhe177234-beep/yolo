"""Train, validate and export a custom detection model."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="YOLO detection training")
    parser.add_argument("--data", required=True, help="Dataset YAML path, or coco8.yaml for smoke testing")
    parser.add_argument("--model", default="models/yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--export", choices=["onnx", "torchscript"])
    args = parser.parse_args()
    if args.epochs < 1 or args.batch < 1:
        parser.error("epochs and batch must be positive")
    from ultralytics import YOLO

    results = YOLO(args.model).train(
        data=args.data,
        epochs=args.epochs,
        batch=args.batch,
        device=args.device,
        imgsz=640,
        workers=0,
        seed=42,
        project="runs/train",
        name="custom",
    )
    best = Path(results.save_dir) / "weights" / "best.pt"
    trained = YOLO(str(best))
    trained.val(data=args.data, device=args.device)
    if args.export:
        trained.export(format=args.export, imgsz=640)
    print(f"Set YOLO_MODEL={best} and restart the server. Select all classes for custom models.")


if __name__ == "__main__":
    main()
