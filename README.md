# tech-news-editor
A small scaffold for a technology news editor that evaluates candidate stories and returns a publish/reject decision.
## Structure

- `src/main.py` parses CLI arguments and runs the editor workflow.
- `src/editor.py` contains the core decision logic.
- `src/validator.py` validates the output payload.
- `src/models.py` defines the Pydantic request/response models.
- `data/sample_input.json` provides a minimal example input.

## Quick start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the sample:
   ```bash
   python -m src.main --input data/sample_input.json
   ```
3. Optional: copy `.env.example` to `.env` and set your API key if you later wire up a real LLM backend.