import argparse
import json
from pathlib import Path

from src.editor import run_editor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the tech news editor")
    parser.add_argument("--input", required=True, help="Path to the input JSON file")
    parser.add_argument("--output", help="Optional output JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    with input_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    result = run_editor(payload)

    if output_path is not None:
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Wrote output to {output_path}")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
