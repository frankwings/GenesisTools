"""VLM-based image comparison and tournament selection.

Uses Vision Language Models to compare rendered images against target images,
enabling automated quality assessment in the VIGA write-run-compare-revise loop.
"""
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

from genesis_tools.image_encoding import get_image_base64
from genesis_tools.llm_client import build_client


def vlm_compare_images(
    image1_path: Union[str, Path],
    image2_path: Union[str, Path],
    target_path: Union[str, Path],
    model: str = "gpt-4o",
) -> int:
    """Use a VLM to compare two images and determine which is closer to target.

    Args:
        image1_path: Path to first rendered image.
        image2_path: Path to second rendered image.
        target_path: Path to target image (or directory containing it).
        model: Vision model to use for comparison.

    Returns:
        1 if image1 is closer to target, 2 if image2 is closer.
    """
    try:
        image1_b64 = get_image_base64(str(image1_path))
        image2_b64 = get_image_base64(str(image2_path))

        # Resolve target path if it's a directory
        target_str = str(target_path)
        if os.path.isdir(target_str):
            for candidate in ["visprompt1.png", "style1.png", "render1.png"]:
                candidate_path = os.path.join(target_str, candidate)
                if os.path.exists(candidate_path):
                    target_str = candidate_path
                    break

        target_b64 = get_image_base64(target_str)

        client = build_client(model)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are an expert at comparing 3D rendered images. "
                            "I will show you two rendered images and a target image. "
                            "Please determine which of the two rendered images is closer "
                            "to the target image in terms of visual similarity, lighting, "
                            "materials, geometry, and overall appearance. "
                            "Respond with only '1' if the first image is closer to the target, "
                            "or '2' if the second image is closer to the target."
                        ),
                    },
                    {"type": "text", "text": "Target image:"},
                    {"type": "image_url", "image_url": {"url": target_b64}},
                    {"type": "text", "text": "Image 1:"},
                    {"type": "image_url", "image_url": {"url": image1_b64}},
                    {"type": "text", "text": "Image 2:"},
                    {"type": "image_url", "image_url": {"url": image2_b64}},
                ],
            }
        ]

        response = client.chat.completions.create(model=model, messages=messages)
        result = response.choices[0].message.content.strip()

        if result == "1":
            return 1
        elif result == "2":
            return 2
        else:
            logging.warning(f"Unexpected VLM response: {result}, defaulting to 1")
            return 1

    except Exception as e:
        logging.warning(f"VLM comparison failed: {e}, defaulting to 1")
        return 1


def tournament_select_best(
    candidate_results: List[Dict],
    target_image_path: Union[str, Path],
    model: str = "gpt-4o",
) -> int:
    """Run a tournament to select the best candidate using VLM comparison.

    Pairs candidates and uses VLM to pick the better match against the target.
    Continues until one winner remains (single-elimination tournament).

    Args:
        candidate_results: List of dicts, each with an 'image' key containing
            a list of rendered image paths.
        target_image_path: Path to the target/reference image.
        model: Vision model name for comparison.

    Returns:
        Index of the winning candidate in the original list.
    """
    if len(candidate_results) <= 1:
        return 0

    current_candidates = list(range(len(candidate_results)))

    while len(current_candidates) > 1:
        next_round = []

        for i in range(0, len(current_candidates), 2):
            if i + 1 >= len(current_candidates):
                # Odd candidate gets a bye
                next_round.append(current_candidates[i])
                continue

            idx1 = current_candidates[i]
            idx2 = current_candidates[i + 1]

            render1_files = candidate_results[idx1].get("image", [])
            render2_files = candidate_results[idx2].get("image", [])

            if not render1_files:
                next_round.append(idx2)
                continue
            if not render2_files:
                next_round.append(idx1)
                continue

            winner = vlm_compare_images(
                str(render1_files[0]),
                str(render2_files[0]),
                str(target_image_path),
                model,
            )

            next_round.append(idx1 if winner == 1 else idx2)

        current_candidates = next_round

    return current_candidates[0]
