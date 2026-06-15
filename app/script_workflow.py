from __future__ import annotations

import time
from typing import Callable


def repair_mojibake(value: object) -> str:
    """Repair common UTF-8 text that was previously decoded as Windows-1252."""
    text = str(value or "")
    markers = ("Ã", "Â", "Ä", "Æ", "á»", "áº", "â€", "ðŸ")
    for _ in range(3):
        current_score = sum(text.count(marker) for marker in markers)
        if current_score == 0:
            break
        candidates = []
        for encoding in ("cp1252", "latin1"):
            try:
                candidate = text.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            score = sum(candidate.count(marker) for marker in markers)
            candidates.append((score, candidate))
        if not candidates:
            break
        score, candidate = min(candidates, key=lambda item: item[0])
        if score >= current_score:
            break
        text = candidate
    return text


def default_workflow_steps() -> list[dict]:
    return [
        {
            "enabled": True,
            "name": "Phân tích đề tài",
            "prompt": (
                "Analyze the topic/source. Identify the audience, angle, key facts, named entities, "
                "timeline, and the strongest visual moments. Do not write the final script yet."
            ),
        },
        {
            "enabled": True,
            "name": "Lập dàn ý",
            "prompt": (
                "Turn the analysis into a coherent video outline with a strong opening, logical body, "
                "specific events, and a concise conclusion. Remove repetition."
            ),
        },
        {
            "enabled": True,
            "name": "Viết script final",
            "prompt": (
                "Write the final voice-over script in natural English. Use complete spoken sentences, "
                "keep factual names and events specific, and output only the narration. Do not include "
                "headings, notes, visual instructions, or workflow commentary."
            ),
        },
    ]


def normalize_workflow_steps(raw_steps) -> list[dict]:
    result = []
    for index, raw in enumerate(raw_steps or [], start=1):
        if not isinstance(raw, dict):
            continue
        prompt = repair_mojibake(raw.get("prompt")).strip()
        if not prompt:
            continue
        result.append(
            {
                "enabled": bool(raw.get("enabled", True)),
                "name": repair_mojibake(raw.get("name") or f"Bước {index}").strip() or f"Bước {index}",
                "prompt": prompt,
            }
        )
    return result


def run_script_workflow(
    source_input: str,
    steps: list[dict],
    settings: dict,
    log: Callable[[str], None] | None = None,
) -> str:
    source_input = str(source_input or "").strip()
    if not source_input:
        raise ValueError("Workflow chưa có chủ đề/dữ liệu đầu vào.")
    enabled_steps = [step for step in normalize_workflow_steps(steps) if step.get("enabled")]
    if not enabled_steps:
        raise ValueError("Workflow không có bước nào đang bật.")

    provider = str(settings.get("keyword_ai_provider") or "auto").strip().lower()
    openai_key = str(settings.get("openai_api_key") or "").strip()
    gemini_key = str(settings.get("gemini_api_key") or "").strip()
    if provider == "auto":
        provider = "openai" if openai_key.startswith("sk-") else "gemini"
    if provider == "openai":
        if not openai_key.startswith("sk-"):
            raise RuntimeError("Workflow OpenAI cần API key bắt đầu bằng sk-.")
        api_key = openai_key
        model = str(settings.get("keyword_ai_model") or "gpt-4.1-mini")
    else:
        if not gemini_key:
            raise RuntimeError("Workflow Gemini chưa có API key.")
        api_key = gemini_key
        model = str(settings.get("gemini_keyword_model") or "gemini-2.5-flash")

    previous = source_input
    total = len(enabled_steps)
    for index, step in enumerate(enabled_steps, start=1):
        name = str(step.get("name") or f"Bước {index}")
        if callable(log):
            log(f"Workflow AI: đang chạy {index}/{total} - {name}")
        prompt = _workflow_prompt(
            source_input=source_input,
            previous_output=previous,
            instruction=str(step.get("prompt") or ""),
            step_name=name,
            step_index=index,
            total_steps=total,
        )
        if provider == "openai":
            previous = _call_openai(api_key, model, prompt)
        else:
            previous = _call_gemini(api_key, model, prompt)
        if not previous.strip():
            raise RuntimeError(f"Workflow bước {index} không trả về nội dung.")
    if callable(log):
        log(f"Workflow AI: hoàn tất {total} bước.")
    return previous.strip()


def _workflow_prompt(
    *,
    source_input: str,
    previous_output: str,
    instruction: str,
    step_name: str,
    step_index: int,
    total_steps: int,
) -> str:
    expanded = (
        instruction.replace("{input}", source_input)
        .replace("{previous}", previous_output)
        .replace("{step}", str(step_index))
    )
    return (
        "You are executing one step in a user-defined script creation workflow.\n"
        f"Step: {step_index}/{total_steps} - {step_name}\n"
        "Follow only this step's instruction. The result will be passed to the next step.\n"
        "Return only the useful output for this step, without explaining the workflow.\n\n"
        f"ORIGINAL USER INPUT:\n{source_input}\n\n"
        f"PREVIOUS STEP OUTPUT:\n{previous_output}\n\n"
        f"THIS STEP INSTRUCTION:\n{expanded}"
    )


def _call_gemini(api_key: str, model: str, prompt: str) -> str:
    import requests

    response = None
    for attempt in range(3):
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.45},
            },
            timeout=180,
        )
        if response.status_code not in {429, 500, 502, 503, 504}:
            break
        if attempt < 2:
            time.sleep(2.5 * (attempt + 1))
    if response is None:
        raise RuntimeError("Gemini workflow không phản hồi.")
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini workflow lỗi {response.status_code}: {response.text[-700:]}")
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini workflow không trả về candidate.")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return "".join(str(part.get("text") or "") for part in parts).strip()


def _call_openai(api_key: str, model: str, prompt: str) -> str:
    import requests

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Execute the workflow step and return only its output."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.45,
        },
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI workflow lỗi {response.status_code}: {response.text[-700:]}")
    return str(response.json()["choices"][0]["message"]["content"] or "").strip()
