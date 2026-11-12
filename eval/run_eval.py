"""Run analyze_frames on every labeled image and write eval/results/<model>_<date>.json.

Usage: uv run python -m eval.run_eval --model claude-sonnet-5-5 --prompt v1
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--prompt", default="v1")
    parser.parse_args()
    raise NotImplementedError


if __name__ == "__main__":
    main()
