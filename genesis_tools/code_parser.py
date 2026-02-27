"""Extract Python code blocks from LLM responses and parse tool calls."""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def extract_code_pieces(text: str, concat: bool = True) -> Union[str, List[str]]:
    """Extract Python code pieces from markdown-formatted text.

    Finds all ```python ... ``` blocks and extracts their content.

    Args:
        text: Model prediction text containing code blocks.
        concat: If True, return concatenated string. If False, return list.

    Returns:
        Concatenated code string (if concat=True) or list of code pieces.
    """
    code_pieces = []
    remaining = text
    while "```python" in remaining:
        st_idx = remaining.index("```python") + 10
        if "```" in remaining[st_idx:]:
            end_idx = remaining.index("```", st_idx)
        else:
            end_idx = len(remaining)
        code_pieces.append(remaining[st_idx:end_idx].strip())
        remaining = remaining[end_idx + 3:].strip()

    if concat:
        return "\n\n".join(code_pieces)
    return code_pieces


def parse_groq_tool_call(content: str) -> Optional[Dict[str, Any]]:
    """Parse Groq's malformed tool call format.

    Groq's Llama models sometimes generate tool calls as:
    <function=tool_name={"arg": "value"}>

    Args:
        content: The response content that may contain a malformed tool call.

    Returns:
        Dictionary with 'name' and 'arguments' keys, or None if not found.
    """
    if not content:
        return None

    patterns = [
        r'<function=(\w+)=(\{.*\})>?',
        r'<function=(\w+)\s+(\{.*\})>?',
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            tool_name = match.group(1)
            try:
                args_str = match.group(2).rstrip(">")
                arguments = json.loads(args_str)
                return {"name": tool_name, "arguments": arguments}
            except json.JSONDecodeError:
                continue

    return None


def save_thought_process(
    memory: List[Dict],
    thought_save: Union[str, Path],
    current_round: Optional[int] = None,
) -> None:
    """Save the current thought process to a JSON file.

    Args:
        memory: List of thought process dictionaries.
        thought_save: Directory (if current_round given) or file path.
        current_round: If provided, saves as {thought_save}/{round+1}.json.
    """
    try:
        if current_round is not None:
            filename = Path(thought_save) / f"{current_round + 1}.json"
        else:
            filename = Path(thought_save)

        filename.parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to save thought process: {e}")
