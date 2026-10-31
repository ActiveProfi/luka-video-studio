"""Extract three local source frames. No network requests or provider calls."""

import argparse
from pathlib import Path

import cv2

from src.orchestrator.artifact_registry import ArtifactRegistry
from src.tools.annotation_toolkit.opencv_tools import extract_frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=20)
    args = parser.parse_args()
    registry = ArtifactRegistry(args.output)
    for offset in (0.05, 2, 3.95):
        frame = extract_frame(args.source, args.start + offset)
        cv2.imwrite(str(registry.artifact_path(f"source_{offset}.jpg")), frame)
    print("Extracted three original frames locally; no API calls.")


if __name__ == "__main__":
    main()
