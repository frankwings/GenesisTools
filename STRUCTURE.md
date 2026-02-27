# GenesisTools Structure

## Package Layout
- `genesis_tools/` — Main package
  - `gif_generator.py` — GIF creation from rendered frames (ping-pong and sequential)
  - `markdown_formatter.py` — Documentation generation with embedded images and git commit hashes
  - `image_encoding.py` — Image to base64 data URL conversion with format preservation
  - `llm_client.py` — Multi-provider LLM client (OpenAI, Claude, Gemini, Groq, Qwen)
  - `code_parser.py` — Extract Python code blocks from LLM responses
  - `vlm_scoring.py` — VLM-based image comparison and tournament selection
  - `config_loader.py` — JSON config loading with environment variable overrides
  - `path_resolver.py` — Config-driven Python environment path resolution
- `tests/` — Unit tests (one per module, all externals mocked)

## Dependencies
- Runtime: pillow, openai
- Dev: pytest, pytest-cov

## Installation
```bash
pip install -e ".[dev]"
```

## Environment Variables
LLM client requires API keys via environment variables:
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`
- `GEMINI_API_KEY`, `GEMINI_BASE_URL`
- `GROQ_API_KEY`, `GROQ_BASE_URL`
- `QWEN_BASE_URL`
- `MESHY_API_KEY`, `VA_API_KEY`
