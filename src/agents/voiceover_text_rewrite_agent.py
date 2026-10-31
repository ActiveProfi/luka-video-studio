"""Voiceover Text Rewrite Agent — переписывание текста урока под AI-озвучку.

Три этапа (только для кнопки «Улучшить ИИ» на шаге редактирования):
1. Анализ — найти ошибки STT, некорректные фразы, проблемы пунктуации и TTS.
2. Переписывание — связный текст для озвучки (без жёсткого лимита шагов).
3. Подгонка тайминга — ровно N шагов под длительность видео.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.config import Settings
from src.providers.llm.runner import complete_with_fallback
from src.services.segment_timing_service import count_timing_steps
from src.services.text_improvement_service import (
    STEP_COUNT_RULES,
    _tts_voice_label,
    load_glossary_snippet,
    parse_improvement_response,
)
from src.services.speech_script_step_tuner import (
    fine_tune_to_exact_steps,
    is_timing_edit_faithful,
    timing_retry_hint_preserve_speech,
)
from src.services.voiceover_text_rules import (
    TTS_VOICEOVER_RULES,
    format_block_guide,
    strip_fillers,
    texts_are_unchanged,
)

logger = logging.getLogger(__name__)

MAX_ANALYSIS_ATTEMPTS = 2
MAX_REWRITE_ATTEMPTS = 3
MAX_TIMING_ATTEMPTS = 8


def _agent_llm_settings(settings: Settings) -> Settings:
    """LLM-профиль только для кнопки «Улучшить ИИ», без влияния на остальные этапы."""
    return settings.model_copy(
        update={
            "llm_provider": settings.cleanup_improve_llm_provider,
            "llm_fallback_order": settings.cleanup_improve_llm_fallback_order,
            "openai_llm_model": settings.cleanup_improve_openai_llm_model,
        }
    )


ANALYSIS_SYSTEM = """Ты эксперт-лингвист и редактор видеоуроков по программе 1С.
Твоя задача — проанализировать текст после распознавания речи (STT) и найти всё, что мешает качественной озвучке.

Ищи:
- ошибки STT (неправильные слова, искажённые термины 1С, пропуски, бессмыслица);
- слова-паразиты и повторы;
- отсутствие или ошибки пунктуации;
- аббревиатуры и числа, которые нельзя читать вслух «как написано»;
- неестественные обороты для диктора.

Будь внимателен: даже если текст «похож на правильный», ищи скрытые ошибки STT.
Ответ — ТОЛЬКО валидный JSON без markdown."""

ANALYSIS_USER = """Исходное распознавание речи (эталон смысла и фактов):
{original_text}

Текущий текст в редакторе:
{current_text}

Термины предметной области 1С:
{glossary}

Верни JSON:
{{
  "issues": [
    {{
      "type": "stt_error|filler|punctuation|tts|grammar|unclear",
      "fragment": "фрагмент из текста",
      "problem": "что не так",
      "suggested_fix": "как исправить для озвучки"
    }}
  ],
  "summary": "краткий итог: сколько и каких проблем найдено"
}}"""

REWRITE_SYSTEM = f"""Ты профессиональный редактор текста для AI-озвучки видеоуроков по 1С.
Перепиши текст так, чтобы его было естественно читать вслух — как сценарий для диктора.

{TTS_VOICEOVER_RULES}

Важно:
- Исправь ВСЕ проблемы из анализа — не оставляй исходные ошибки STT.
- Сохрани смысл, порядок действий, числа и факты из исходника.
- Не добавляй новых шагов урока, которых не было в исходнике.
- Текст должен заметно отличаться от сырого STT, если в анализе есть проблемы.

Ответ — ТОЛЬКО валидный JSON без markdown."""

REWRITE_USER = """Длительность урока: {duration:.1f} с.
Озвучка: {tts_provider}, голос {tts_voice}.

Результаты анализа:
{analysis_json}

Исходное распознавание (смысл и факты):
{original_text}

Текущий текст:
{current_text}

Термины 1С:
{glossary}

Перепиши текст целиком для озвучки. Примени все исправления из анализа.

Верни JSON:
{{
  "text": "полный переписанный текст",
  "changes_applied": ["что изменено 1", "что изменено 2"]
}}"""

REWRITE_RETRY_USER = """Попытка {attempt}. Текст почти не изменился, а в анализе найдены проблемы.
ОБЯЗАТЕЛЬНО внеси правки: исправь ошибки STT, расшифруй аббревиатуры, расставь пунктуацию.

Анализ:
{analysis_json}

Исходник:
{original_text}

Перепиши заново (не копируй текущий текст дословно):

Верни JSON:
{{
  "text": "...",
  "changes_applied": ["..."]
}}"""

TIMING_SYSTEM = f"""Ты редактор текста для видеоуроков по 1С.
На вход уже приходит ГОТОВЫЙ Speech Script для озвучки.
Твоя задача ТОЛЬКО подогнать длину под тайминг — ровно указанное число шагов.

ГЛАВНОЕ:
1) В ответе РОВНО указанное число шагов — не больше и не меньше.
2) СОХРАНИ Speech Script: аббревиатуры в произносимой форме («эн дэ эс», «один эс» и т.п.).
3) Меняй только объём УЖЕ существующих предложений (короче/чуть подробнее те же фразы).
4) СТРОГО ЗАПРЕЩЕНО:
   - добавлять новые предложения;
   - дописывать новый финал / концовку, которой не было в Speech Script;
   - добавлять новые факты, шаги урока или пояснения «от себя»;
   - пересказывать текст заново другими словами целиком.
5) Число предложений должно остаться тем же (или меньше при сокращении), но не больше.

{TTS_VOICEOVER_RULES}

{STEP_COUNT_RULES}

Перед ответом пересчитай шаги. Поле "steps" должно совпасть с текстом.
Ответ — ТОЛЬКО валидный JSON без markdown."""

TIMING_USER = """Урок: {duration:.1f} с. НУЖНО РОВНО {budget_steps} ШАГОВ (в черновике {draft_steps}).
1 шаг ≈ {seconds_per_step:.3f} с.

Границы блоков озвучки:
{block_guide}

Speech Script — ЕДИНСТВЕННЫЙ источник текста (не дописывай ничего нового в конце):
{draft_text}

Факты для сверки (не добавляй из этого куски, которых нет в Speech Script выше):
{original_excerpt}

Верни JSON:
{{
  "text": "тот же Speech Script, только длина подогнана; без новых предложений",
  "steps": {budget_steps},
  "notes": "как изменили длину внутри существующих фраз"
}}"""

TIMING_RETRY_USER = """Попытка {attempt} из {max_attempts}. Было {got_steps} шагов, нужно РОВНО {budget_steps}.
{hint}

{step_rules}

Работай от этого текста. Не добавляй новых предложений и не пиши новый финал:
{draft_text}

Верни JSON с "steps": {budget_steps}."""


def _finalize_exact_timing(text: str, budget_steps: int, *, notes: str, attempts: int) -> dict[str, Any]:
    """Довести до ровно budget_steps и проверить совпадение."""
    fitted = fine_tune_to_exact_steps(text, budget_steps)
    improved_steps = count_timing_steps(fitted)
    if improved_steps != budget_steps:
        raise ValueError(
            f"Тайминг не совпал: {improved_steps} шагов вместо {budget_steps}"
        )
    return {
        "text": fitted,
        "notes": notes,
        "budget_steps": budget_steps,
        "improved_steps": improved_steps,
        "budget_matched": True,
        "budget_exceeded": False,
        "attempts": attempts,
    }

def _parse_json_response(raw: str) -> dict[str, Any]:
    cleaned = str(raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def parse_analysis_response(raw: str) -> dict[str, Any]:
    data = _parse_json_response(raw)
    issues = list(data.get("issues") or [])
    summary = str(data.get("summary", "")).strip()
    if not summary and issues:
        summary = f"Найдено проблем: {len(issues)}"
    return {"issues": issues, "summary": summary or "Анализ выполнен"}


def parse_rewrite_response(raw: str) -> dict[str, Any]:
    data = _parse_json_response(raw)
    text = str(data.get("text", "")).strip()
    if not text:
        raise ValueError("Агент переписывания не вернул текст")
    changes = [str(item).strip() for item in (data.get("changes_applied") or []) if str(item).strip()]
    return {"text": text, "changes_applied": changes}


async def analyze_voiceover_text(
    settings: Settings,
    *,
    original_text: str,
    current_text: str,
) -> tuple[dict[str, Any], str]:
    glossary = load_glossary_snippet(settings)
    preprocessed = strip_fillers(current_text)
    user_prompt = ANALYSIS_USER.format(
        original_text=original_text or "—",
        current_text=preprocessed or current_text or "—",
        glossary=glossary,
    )
    last_error = ""
    for attempt in range(1, MAX_ANALYSIS_ATTEMPTS + 1):
        try:
            raw, provider = await complete_with_fallback(settings, ANALYSIS_SYSTEM, user_prompt)
            parsed = parse_analysis_response(raw)
            logger.info(
                "Voiceover agent: анализ — %s проблем (попытка %s)",
                len(parsed["issues"]),
                attempt,
            )
            return parsed, provider
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            last_error = str(exc)
            logger.warning("Voiceover agent анализ попытка %s: %s", attempt, exc)
    raise ValueError(f"Не удалось проанализировать текст: {last_error}")


async def rewrite_for_voiceover(
    settings: Settings,
    *,
    original_text: str,
    current_text: str,
    analysis: dict[str, Any],
    duration: float,
) -> tuple[dict[str, Any], str]:
    glossary = load_glossary_snippet(settings)
    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)
    base_current = strip_fillers(current_text) or current_text

    last_error = ""
    provider = settings.llm_provider
    for attempt in range(1, MAX_REWRITE_ATTEMPTS + 1):
        if attempt == 1:
            user_prompt = REWRITE_USER.format(
                duration=duration,
                tts_provider=settings.tts_provider,
                tts_voice=_tts_voice_label(settings),
                analysis_json=analysis_json,
                original_text=original_text or "—",
                current_text=base_current or "—",
                glossary=glossary,
            )
        else:
            user_prompt = REWRITE_RETRY_USER.format(
                attempt=attempt,
                analysis_json=analysis_json,
                original_text=original_text or base_current,
            )
        try:
            raw, provider = await complete_with_fallback(settings, REWRITE_SYSTEM, user_prompt)
            parsed = parse_rewrite_response(raw)
            issues_count = len(analysis.get("issues") or [])
            if issues_count > 0 and texts_are_unchanged(base_current, parsed["text"]):
                raise ValueError("Текст не изменился после анализа с проблемами")
            logger.info(
                "Voiceover agent: переписывание — %s изменений (попытка %s)",
                len(parsed["changes_applied"]),
                attempt,
            )
            return parsed, provider
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("Voiceover agent переписывание попытка %s: %s", attempt, exc)

    raise ValueError(f"Не удалось переписать текст для озвучки: {last_error}")


async def fit_voiceover_timing(
    settings: Settings,
    *,
    draft_text: str,
    original_text: str,
    duration: float,
    budget_steps: int,
    segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    draft_steps = count_timing_steps(draft_text)
    slot = max(0.1, float(duration))
    original_excerpt = (original_text or draft_text)[:1500]
    block_guide = format_block_guide(segments)

    if draft_steps == budget_steps:
        return {
            "text": draft_text,
            "notes": "Черновик уже совпал с бюджетом шагов",
            "budget_steps": budget_steps,
            "improved_steps": draft_steps,
            "budget_matched": True,
            "budget_exceeded": False,
            "attempts": 0,
        }, settings.llm_provider

    # Сначала консервативная доводка самого Speech Script — без переписывания ИИ.
    try:
        return (
            _finalize_exact_timing(
                draft_text,
                budget_steps,
                notes="Тайминг подогнан по Speech Script без новых предложений",
                attempts=0,
            ),
            settings.llm_provider,
        )
    except ValueError:
        logger.info(
            "Voiceover agent: локальная доводка не закрыла бюджет (%s → %s), пробуем ИИ",
            draft_steps,
            budget_steps,
        )

    user_prompt = TIMING_USER.format(
        duration=slot,
        budget_steps=budget_steps,
        draft_steps=draft_steps,
        seconds_per_step=round(slot / budget_steps, 4),
        block_guide=block_guide,
        draft_text=draft_text,
        original_excerpt=original_excerpt or "—",
    )

    last_error = ""
    last_steps = draft_steps
    provider = settings.llm_provider
    working_text = draft_text
    best_text = draft_text
    best_steps = draft_steps
    best_notes = "Подгонка тайминга Speech Script"

    for attempt in range(1, MAX_TIMING_ATTEMPTS + 1):
        prompt = user_prompt if attempt == 1 else TIMING_RETRY_USER.format(
            attempt=attempt,
            max_attempts=MAX_TIMING_ATTEMPTS,
            got_steps=last_steps,
            budget_steps=budget_steps,
            hint=timing_retry_hint_preserve_speech(budget_steps, last_steps),
            step_rules=STEP_COUNT_RULES,
            draft_text=working_text if is_timing_edit_faithful(draft_text, working_text) else draft_text,
        )
        try:
            raw, provider = await complete_with_fallback(settings, TIMING_SYSTEM, prompt)
            try:
                candidate = _parse_json_response(raw)
                candidate_text = str(candidate.get("text", "")).strip()
                if candidate_text and is_timing_edit_faithful(draft_text, candidate_text):
                    candidate_steps = count_timing_steps(candidate_text)
                    working_text = candidate_text
                    last_steps = candidate_steps
                    if abs(candidate_steps - budget_steps) < abs(best_steps - budget_steps):
                        best_text = candidate_text
                        best_steps = candidate_steps
                        best_notes = str(candidate.get("notes") or best_notes).strip()
                elif candidate_text:
                    logger.warning(
                        "Voiceover agent тайминг: ответ ИИ отклонён — слишком далеко от Speech Script"
                    )
                    last_error = "ИИ добавил новый текст / предложения вне Speech Script"
                    working_text = draft_text
            except (json.JSONDecodeError, ValueError, KeyError, TypeError):
                pass

            parsed = parse_improvement_response(raw, budget_steps=budget_steps)
            if not is_timing_edit_faithful(draft_text, parsed["text"]):
                raise ValueError("ИИ изменил текст слишком сильно или добавил новые предложения")
            finalized = _finalize_exact_timing(
                parsed["text"],
                budget_steps,
                notes=parsed["notes"] or best_notes,
                attempts=attempt,
            )
            if not is_timing_edit_faithful(draft_text, finalized["text"]):
                raise ValueError("После доводки текст отошёл от Speech Script")
            return finalized, provider
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if "ИИ вернул" in last_error:
                match = re.search(r"ИИ вернул (\d+) шагов", last_error)
                if match:
                    last_steps = int(match.group(1))
            logger.warning("Voiceover agent тайминг попытка %s/%s: %s", attempt, MAX_TIMING_ATTEMPTS, exc)

    # Финал: только верный Speech Script (не выдуманный финал).
    base = best_text if is_timing_edit_faithful(draft_text, best_text) else draft_text
    try:
        finalized = _finalize_exact_timing(
            base,
            budget_steps,
            notes=(
                f"{best_notes}. Точная доводка до {budget_steps} шагов "
                "без новых предложений вне Speech Script."
            ),
            attempts=MAX_TIMING_ATTEMPTS,
        )
        return finalized, provider
    except ValueError as exc:
        logger.error("Voiceover agent: точный тайминг не подобран: %s; last=%s", exc, last_error)
        raise ValueError(
            f"Не удалось подогнать Speech Script ровно на {budget_steps} шагов "
            f"без новых предложений (лучший вариант: {best_steps}). {exc}"
        ) from exc


async def run_voiceover_text_rewrite_async(
    settings: Settings,
    *,
    full_text: str,
    full_original: str,
    duration: float,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Полный цикл агента: анализ → переписывание → подгонка шагов."""
    current = str(full_text or "").strip()
    original = str(full_original or current).strip()
    if not current:
        raise ValueError("Текст урока пустой")

    agent_settings = _agent_llm_settings(settings)
    budget_steps = max(1, count_timing_steps(original or current))
    slot = max(0.1, float(duration))

    analysis, analysis_provider = await analyze_voiceover_text(
        agent_settings,
        original_text=original,
        current_text=current,
    )
    rewrite, rewrite_provider = await rewrite_for_voiceover(
        agent_settings,
        original_text=original,
        current_text=current,
        analysis=analysis,
        duration=slot,
    )
    timing, timing_provider = await fit_voiceover_timing(
        agent_settings,
        draft_text=rewrite["text"],
        original_text=original,
        duration=slot,
        budget_steps=budget_steps,
        segments=segments,
    )

    changes = list(rewrite.get("changes_applied") or [])
    notes_parts = [analysis.get("summary", "")]
    if timing.get("notes"):
        notes_parts.append(str(timing["notes"]))
    if changes:
        notes_parts.append("Изменения: " + "; ".join(changes[:5]))

    return {
        "text": timing["text"],
        "notes": ". ".join(part for part in notes_parts if part),
        "provider": timing_provider or rewrite_provider or analysis_provider,
        "budget_steps": budget_steps,
        "improved_steps": timing.get("improved_steps", count_timing_steps(timing["text"])),
        "budget_matched": bool(timing.get("budget_matched", True)),
        "budget_exceeded": bool(timing.get("budget_exceeded", False)),
        "attempts": int(timing.get("attempts") or 0),
        "analysis_summary": analysis.get("summary", ""),
        "issues_found": len(analysis.get("issues") or []),
        "changes_applied": changes,
        "agent": "voiceover_text_rewrite",
        "phases": {
            "analysis_issues": len(analysis.get("issues") or []),
            "rewrite_changes": len(changes),
            "timing_attempts": int(timing.get("attempts") or 0),
        },
    }
