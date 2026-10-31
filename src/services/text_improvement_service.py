"""ИИ-улучшение текста блока с учётом тайминга и будущей озвучки."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from src.config import Settings
from src.providers.llm.runner import complete_with_fallback
from src.services.segment_timing_service import count_timing_steps
from src.services.speech_timing_service import build_segment_timing_info, segment_slot_seconds

logger = logging.getLogger(__name__)

MAX_IMPROVE_ATTEMPTS = 4

STEP_COUNT_RULES = """Как считать шаги (это же число «бюджет» и «сейчас» в интерфейсе):
1. Разбей текст на слова по пробелам.
2. Шаги = сумма длин всех слов + (число слов − 1).
   Каждый символ слова = 1 шаг, каждый пробел между словами = 1 шаг.
Примеры:
- «НДС» → 1 слово, 3 символа → 3 шага
- «эн дэ эс» → 3 слова (2+1+1 символов) + 2 паузы → 6 шагов
- «мы открываем» → 2 слова (2+8) + 1 пауза → 11 шагов"""

SYSTEM_PROMPT = f"""Ты редактор текста для видеоуроков по программе 1С (бухгалтерия, НДС, УСН).
Текст пойдёт в AI-озвучку и должен занять ровно тот же тайм-слот, что и исходное видео (паузы не вырезаются).

ГЛАВНОЕ ПРАВИЛО (обязательно): в ответе должно быть РОВНО указанное число шагов — не больше и не меньше.
Если шагов больше — озвучка не влезет в блок и видео уедет. Если меньше — будет пустота и рассинхрон.

{STEP_COUNT_RULES}

Дополнительно:
- Сохраняй смысл, факты, числа из исходника.
- Убирай слова-паразиты, повторы, ошибки распознавания.
- Для TTS: аббревиатуры часто пишут с пробелами между буквами (НДС → «эн дэ эс», УСН → «у эс эн», 1С → «один эс»).
  Расшифровка занимает больше шагов — компенсируй сокращением других слов, чтобы итог = бюджет.
- Не добавляй новых фактов.

Перед ответом пересчитай шаги своего текста. В JSON укажи поле "steps" — должно совпасть с "text".

Ответ — ТОЛЬКО валидный JSON без markdown."""

USER_PROMPT_TEMPLATE = """Тайм-блок: {start:.1f}–{end:.1f} с (длительность {slot_seconds:.1f} с).
НУЖНО РОВНО {budget_steps} ШАГОВ (сейчас в тексте {current_steps}, это неверно — исправь).
1 шаг ≈ {seconds_per_step:.3f} с речи в этом блоке.
Озвучка: {tts_provider}, голос {tts_voice}.

Исходное распознавание (смысл и факты):
{original_text}

Текущий текст блока:
{current_text}

Термины 1С:
{glossary}

Верни JSON:
{{
  "text": "текст для озвучки",
  "steps": {budget_steps},
  "notes": "кратко: что изменено"
}}"""

RETRY_PROMPT_TEMPLATE = """Попытка {attempt} из {max_attempts}. ОШИБКА: в прошлом ответе было {got_steps} шагов, а нужно РОВНО {budget_steps}.
Разница: {delta:+d} шагов. {hint}

{step_rules}

Исходный смысл:
{original_text}

Перепиши текст. В JSON поле "steps" должно быть {budget_steps}, и текст должен давать ровно столько шагов.

Верни JSON:
{{
  "text": "...",
  "steps": {budget_steps},
  "notes": "..."
}}"""


def load_glossary_snippet(settings: Settings, limit: int = 30) -> str:
    path = Path(settings.domain_glossary_path)
    if not path.exists():
        return "НДС, УСН, 1С, документ, проведение, отчёт"
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    terms = [line.lstrip("#").strip() for line in lines if line.strip() and not line.startswith("#")]
    return ", ".join(terms[:limit]) if terms else "НДС, УСН, 1С"


def _tts_voice_label(settings: Settings) -> str:
    if settings.tts_provider == "yandex":
        return settings.yandex_tts_voice
    if settings.tts_provider == "openai":
        return settings.openai_tts_voice
    if settings.tts_provider == "elevenlabs":
        return settings.elevenlabs_voice_id or "default"
    return settings.tts_provider


def build_segment_improvement_context(segment: dict[str, Any]) -> dict[str, Any]:
    start = float(segment["start"])
    end = float(segment["end"])
    slot = segment_slot_seconds(start, end)
    current = str(segment.get("text", "")).strip()
    original = str(segment.get("original_text") or current).strip()
    budget_steps = max(1, count_timing_steps(original or current))
    current_steps = count_timing_steps(current)
    timing = build_segment_timing_info(start, end, current, original_text=original)
    return {
        "start": start,
        "end": end,
        "slot_seconds": slot,
        "budget_steps": budget_steps,
        "current_steps": current_steps,
        "seconds_per_step": round(slot / budget_steps, 4),
        "original_text": original,
        "current_text": current,
        "timing_exceeded": timing.get("timing_exceeded", False),
    }


def _retry_hint(budget_steps: int, got_steps: int) -> str:
    delta = got_steps - budget_steps
    if delta > 0:
        return (
            f"Сократи текст примерно на {delta} шаг(ов): убери лишние слова, "
            "сократи расшифровки аббревиатур или используй более короткие синонимы."
        )
    need = -delta
    return (
        f"Добавь примерно {need} шаг(ов): чуть подробнее формулировки, "
        "пробелы в аббревиатурах для TTS (эн дэ эс), союзы «и», «то есть», без новых фактов."
    )


def parse_improvement_response(raw: str, *, budget_steps: int) -> dict[str, str]:
    cleaned = str(raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    text = str(data.get("text", "")).strip()
    if not text:
        raise ValueError("ИИ не вернул текст блока")
    notes = str(data.get("notes", "")).strip()
    actual_steps = count_timing_steps(text)
    claimed = data.get("steps")
    if claimed is not None and int(claimed) != actual_steps:
        logger.warning("ИИ указал steps=%s, фактически %s", claimed, actual_steps)
    if actual_steps != budget_steps:
        raise ValueError(
            f"ИИ вернул {actual_steps} шагов, нужно ровно {budget_steps}. "
            "Повторяем запрос с уточнением."
        )
    return {"text": text, "notes": notes}


async def improve_segment_text_async(
    settings: Settings,
    segment: dict[str, Any],
) -> dict[str, Any]:
    ctx = build_segment_improvement_context(segment)
    budget = ctx["budget_steps"]
    user_prompt = USER_PROMPT_TEMPLATE.format(
        start=ctx["start"],
        end=ctx["end"],
        slot_seconds=ctx["slot_seconds"],
        budget_steps=budget,
        current_steps=ctx["current_steps"],
        seconds_per_step=ctx["seconds_per_step"],
        tts_provider=settings.tts_provider,
        tts_voice=_tts_voice_label(settings),
        original_text=ctx["original_text"] or "—",
        current_text=ctx["current_text"] or "—",
        glossary=load_glossary_snippet(settings),
    )

    last_error = ""
    last_steps = 0
    provider = settings.llm_provider

    for attempt in range(1, MAX_IMPROVE_ATTEMPTS + 1):
        prompt = user_prompt if attempt == 1 else RETRY_PROMPT_TEMPLATE.format(
            attempt=attempt,
            max_attempts=MAX_IMPROVE_ATTEMPTS,
            got_steps=last_steps,
            budget_steps=budget,
            delta=last_steps - budget,
            hint=_retry_hint(budget, last_steps),
            step_rules=STEP_COUNT_RULES,
            original_text=ctx["original_text"] or ctx["current_text"],
        )
        raw, provider = await complete_with_fallback(settings, SYSTEM_PROMPT, prompt)
        try:
            parsed = parse_improvement_response(raw, budget_steps=budget)
            improved_steps = count_timing_steps(parsed["text"])
            return {
                "text": parsed["text"],
                "notes": parsed["notes"],
                "provider": provider,
                "budget_steps": budget,
                "improved_steps": improved_steps,
                "budget_matched": True,
                "budget_exceeded": False,
                "attempts": attempt,
            }
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if "ИИ вернул" in last_error:
                match = re.search(r"ИИ вернул (\d+) шагов", last_error)
                if match:
                    last_steps = int(match.group(1))
            logger.warning("ИИ улучшение попытка %s/%s: %s", attempt, MAX_IMPROVE_ATTEMPTS, exc)

    raise ValueError(
        f"Не удалось подобрать текст ровно на {budget} шагов "
        f"(последний ответ: {last_steps} шагов). {last_error}"
    )


FULL_SYSTEM_PROMPT = f"""Ты редактор полного текста видеоурока по программе 1С (бухгалтерия, НДС, УСН).
Текст целиком пойдёт в AI-озвучку и должен уложиться в общую длительность исходного видео (паузы не вырезаются).

ГЛАВНОЕ ПРАВИЛО (обязательно): в ответе должно быть РОВНО указанное число шагов на весь урок — не больше и не меньше.

{STEP_COUNT_RULES}

Что нужно сделать (это важнее «минимальных правок»):
- Исправь явные ошибки распознавания речи: неправильные слова, пропуски, «э-э», «ну», повторы.
- Сохрани смысл, порядок действий, числа и термины из исходника.
- Подготовь текст к озвучке: аббревиатуры часто с пробелами (НДС → «эн дэ эс», УСН → «у эс эн», 1С → «один эс»).
  Расшифровка занимает больше шагов — сокращай другие слова, чтобы итог = бюджет.
- Не добавляй новых фактов и шагов, которых не было в исходнике.
- Текст должен читаться связно от начала до конца — это один урок, не отдельные куски.

Перед ответом пересчитай шаги. В JSON поле "steps" должно совпасть с текстом.

Ответ — ТОЛЬКО валидный JSON без markdown."""

FULL_USER_PROMPT_TEMPLATE = """Урок: {duration:.1f} с. НУЖНО РОВНО {budget_steps} ШАГОВ на весь текст (сейчас {current_steps}).
1 шаг ≈ {seconds_per_step:.3f} с речи.
Озвучка: {tts_provider}, голос {tts_voice}.

Ориентир по тайм-блокам (после сохранения текст автоматически режется по этим границам):
{block_guide}

Исходное распознавание целиком (смысл и факты):
{original_text}

Текущий текст урока:
{current_text}

Термины 1С:
{glossary}

Верни JSON:
{{
  "text": "полный текст для озвучки",
  "steps": {budget_steps},
  "notes": "кратко: что исправлено (STT, TTS, смысл)"
}}"""

FULL_RETRY_PROMPT_TEMPLATE = """Попытка {attempt} из {max_attempts}. ОШИБКА: было {got_steps} шагов, нужно РОВНО {budget_steps}.
Разница: {delta:+d} шагов. {hint}

{step_rules}

Исходный смысл (фрагмент):
{original_excerpt}

Перепиши весь текст урока. JSON: "steps": {budget_steps}.

Верни JSON:
{{
  "text": "...",
  "steps": {budget_steps},
  "notes": "..."
}}"""


def _format_block_guide(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, seg in enumerate(segments):
        original = str(seg.get("original_text") or seg.get("text", "")).strip()
        budget = max(1, count_timing_steps(original))
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        lines.append(f"- Блок {index + 1}: {start:.1f}–{end:.1f} с, ~{budget} шагов")
    return "\n".join(lines) if lines else "—"


def build_full_text_improvement_context(
    *,
    full_text: str,
    full_original: str,
    duration: float,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    current = str(full_text or "").strip()
    original = str(full_original or current).strip()
    budget_steps = max(1, count_timing_steps(original or current))
    current_steps = count_timing_steps(current)
    slot = max(0.1, float(duration))
    return {
        "duration": slot,
        "budget_steps": budget_steps,
        "current_steps": current_steps,
        "seconds_per_step": round(slot / budget_steps, 4),
        "original_text": original,
        "current_text": current,
        "block_guide": _format_block_guide(segments),
    }


async def improve_full_text_async(
    settings: Settings,
    *,
    full_text: str,
    full_original: str,
    duration: float,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    ctx = build_full_text_improvement_context(
        full_text=full_text,
        full_original=full_original,
        duration=duration,
        segments=segments,
    )
    budget = ctx["budget_steps"]
    user_prompt = FULL_USER_PROMPT_TEMPLATE.format(
        duration=ctx["duration"],
        budget_steps=budget,
        current_steps=ctx["current_steps"],
        seconds_per_step=ctx["seconds_per_step"],
        tts_provider=settings.tts_provider,
        tts_voice=_tts_voice_label(settings),
        block_guide=ctx["block_guide"],
        original_text=ctx["original_text"] or "—",
        current_text=ctx["current_text"] or "—",
        glossary=load_glossary_snippet(settings),
    )

    last_error = ""
    last_steps = 0
    provider = settings.llm_provider
    original_excerpt = ctx["original_text"][:1200] if ctx["original_text"] else ctx["current_text"][:1200]

    for attempt in range(1, MAX_IMPROVE_ATTEMPTS + 1):
        prompt = user_prompt if attempt == 1 else FULL_RETRY_PROMPT_TEMPLATE.format(
            attempt=attempt,
            max_attempts=MAX_IMPROVE_ATTEMPTS,
            got_steps=last_steps,
            budget_steps=budget,
            delta=last_steps - budget,
            hint=_retry_hint(budget, last_steps),
            step_rules=STEP_COUNT_RULES,
            original_excerpt=original_excerpt or "—",
        )
        raw, provider = await complete_with_fallback(settings, FULL_SYSTEM_PROMPT, prompt)
        try:
            parsed = parse_improvement_response(raw, budget_steps=budget)
            improved_steps = count_timing_steps(parsed["text"])
            return {
                "text": parsed["text"],
                "notes": parsed["notes"],
                "provider": provider,
                "budget_steps": budget,
                "improved_steps": improved_steps,
                "budget_matched": True,
                "budget_exceeded": False,
                "attempts": attempt,
            }
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if "ИИ вернул" in last_error:
                match = re.search(r"ИИ вернул (\d+) шагов", last_error)
                if match:
                    last_steps = int(match.group(1))
            logger.warning("ИИ улучшение (весь текст) попытка %s/%s: %s", attempt, MAX_IMPROVE_ATTEMPTS, exc)

    raise ValueError(
        f"Не удалось подобрать текст ровно на {budget} шагов "
        f"(последний ответ: {last_steps} шагов). {last_error}"
    )
