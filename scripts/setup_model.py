"""Download trusted official weights explicitly before serving requests."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="yolo11n.pt", choices=["yolo11n.pt", "yolo11s.pt"])
    parser.add_argument("--output", default="models")
    args = parser.parse_args()
    from ultralytics import YOLO
    from ultralytics.utils.downloads import attempt_download_asset

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / args.model
    attempt_download_asset(str(target))
    model = YOLO(str(target))
    print(f"Ready: {target} ({len(model.names)} classes)")


if __name__ == "__main__":
    main()
