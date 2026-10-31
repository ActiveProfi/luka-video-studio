"""Шаг 3: технический конвейер подготовки текста к TTS."""

from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any

from src.config import Settings
from src.domain.contracts import utc_now_iso
from src.providers.llm.runner import complete_with_fallback
from src.services.accounting_terms_rules import apply_accounting_term_rules
from src.services.speech_duration_estimator import attach_duration_report
from src.services.text_cleanup_rules import clean_technical_noise
from src.services.tts_normalization_rules import apply_tts_normalization_rules
from src.services.tts_preparation_types import TextChange

logger = logging.getLogger(__name__)

TTS_PREPARATION_REPORT = "tts_preparation_report.json"
SPEECH_SCRIPT_FILE = "speech_script.json"

MINIMAL_EDIT_SYSTEM = """Ты выполняешь минимальную техническую редактуру текста видеоурока по 1С.

Разрешено только:
- исправить явные грамматические ошибки;
- расставить пунктуацию;
- удалить случайные повторы слов;
- удалить речевой мусор, который не убрали правила.

Запрещено:
- переписывать стиль автора;
- менять порядок объяснения;
- заменять слова синонимами без необходимости;
- сокращать объяснение;
- добавлять новые пояснения или факты;
- менять бухгалтерские термины.

Если предложение нормальное, оставь его без изменений.
Ответ — только валидный JSON без markdown."""

MINIMAL_EDIT_USER = """Текущий текст:
{text}

Верни JSON:
{{
  "text": "тот же текст с минимальными исправлениями",
  "notes": "что исправлено"
}}"""

COMPACT_EDIT_USER = """После минимальной редактуры часть фрагментов вышла за бюджет длительности.
Сделай только компактную правку этих мест: убери лишние слова и повторы, но не меняй смысл.

Текущий текст:
{text}

Проблемные фрагменты:
{problem_changes}

Верни JSON:
{{
  "text": "текст после компактной минимальной правки",
  "notes": "что сокращено"
}}"""

AUDIT_SYSTEM = """Ты аудитор результата подготовки текста к озвучке.
Ты НЕ переписываешь текст. Только проверяешь, сохранились ли смысл, порядок действий, факты и стиль автора.
Ответ — только валидный JSON без markdown."""

AUDIT_USER = """Исходный текст:
{original_text}

Подготовленный текст:
{prepared_text}

Ответь JSON:
{{
  "meaning_changed": false,
  "order_changed": false,
  "new_facts_added": false,
  "important_details_removed": false,
  "style_changed": false,
  "approved": true,
  "notes": "краткое объяснение"
}}"""


def _agent_llm_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "llm_provider": settings.cleanup_improve_llm_provider,
            "llm_fallback_order": settings.cleanup_improve_llm_fallback_order,
            "openai_llm_model": settings.cleanup_improve_openai_llm_model,
        }
    )


def _parse_json_response(raw: str) -> dict[str, Any]:
    cleaned = str(raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def build_text_diff_changes(before: str, after: str, *, stage: str, reason: str) -> list[TextChange]:
    """Вернуть только изменённые фрагменты, насколько возможно по предложениям."""
    if before == after:
        return []

    before_sentences = _split_sentences(before)
    after_sentences = _split_sentences(after)
    if before_sentences and len(before_sentences) == len(after_sentences):
        changes: list[TextChange] = []
        for old, new in zip(before_sentences, after_sentences, strict=True):
            if old != new:
                changes.append(TextChange(before=old, after=new, stage=stage, reason=reason))
        return changes

    matcher = difflib.SequenceMatcher(a=before, b=after)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = before[max(0, i1 - 60) : min(len(before), i2 + 60)].strip()
        new = after[max(0, j1 - 60) : min(len(after), j2 + 60)].strip()
        if old or new:
            changes.append(TextChange(before=old, after=new, stage=stage, reason=reason))
    return changes


async def _minimal_llm_edit(
    settings: Settings,
    text: str,
    *,
    problem_changes: list[TextChange] | None = None,
) -> tuple[str, list[TextChange], str, str]:
    if problem_changes:
        problems = json.dumps([item.to_dict() for item in problem_changes], ensure_ascii=False, indent=2)
        prompt = COMPACT_EDIT_USER.format(text=text, problem_changes=problems)
        stage = "3.3 minimal_llm_edit_retry"
        reason = "Компактная минимальная правка после контроля длительности"
    else:
        prompt = MINIMAL_EDIT_USER.format(text=text)
        stage = "3.3 minimal_llm_edit"
        reason = "Минимальная LLM-редактура"

    raw, provider = await complete_with_fallback(settings, MINIMAL_EDIT_SYSTEM, prompt)
    data = _parse_json_response(raw)
    edited = str(data.get("text", "")).strip()
    if not edited:
        raise ValueError("LLM не вернула текст после минимальной редактуры")

    notes = str(data.get("notes", "")).strip()
    changes = build_text_diff_changes(text, edited, stage=stage, reason=notes or reason)
    return edited, changes, notes, provider


async def _audit_result(settings: Settings, original_text: str, prepared_text: str) -> tuple[dict[str, Any], str]:
    raw, provider = await complete_with_fallback(
        settings,
        AUDIT_SYSTEM,
        AUDIT_USER.format(original_text=original_text or "—", prepared_text=prepared_text or "—"),
    )
    data = _parse_json_response(raw)
    result = {
        "meaning_changed": bool(data.get("meaning_changed", False)),
        "order_changed": bool(data.get("order_changed", False)),
        "new_facts_added": bool(data.get("new_facts_added", False)),
        "important_details_removed": bool(data.get("important_details_removed", False)),
        "style_changed": bool(data.get("style_changed", False)),
        "approved": bool(data.get("approved", True)),
        "notes": str(data.get("notes", "")).strip(),
    }
    return result, provider


async def run_tts_preparation_pipeline_async(
    settings: Settings,
    *,
    job_id: str,
    full_text: str,
    full_original: str,
) -> dict[str, Any]:
    """Подготовка текста к TTS: правила без кардинальной переписки LLM."""
    original = str(full_original or full_text or "").strip()
    current = str(full_text or "").strip()
    if not current:
        raise ValueError("Текст урока пустой")

    all_changes: list[TextChange] = []
    phases: list[dict[str, Any]] = []

    cleaned, changes = clean_technical_noise(current)
    all_changes.extend(changes)
    phases.append({"id": "3.1", "name": "technical_clean", "changes": len(changes), "llm": False})
    current = cleaned

    terms_fixed, changes = apply_accounting_term_rules(current, settings)
    all_changes.extend(changes)
    phases.append({"id": "3.2", "name": "term_correction", "changes": len(changes), "llm": False})
    current = terms_fixed

    # Без LLM: не переписываем стиль и смысл, только готовим к озвучке.
    phases.append(
        {
            "id": "3.3",
            "name": "minimal_llm_edit",
            "changes": 0,
            "llm": False,
            "skipped": True,
            "reason": "Без кардинальной переписки — только правила озвучки",
        }
    )
    minimal_notes = "Без LLM-переписывания: исходный текст сохранён, применена подготовка к озвучке"

    tts_ready, changes = apply_tts_normalization_rules(current, settings)
    all_changes.extend(changes)
    phases.append({"id": "3.4", "name": "tts_normalization", "changes": len(changes), "llm": False})
    current = tts_ready

    all_changes = attach_duration_report(all_changes, settings)
    problem_changes = [item for item in all_changes if item.budget_status == "needs_review"]
    phases.append(
        {
            "id": "3.5",
            "name": "duration_budget",
            "changes": len(all_changes),
            "needs_review": len(problem_changes),
            "llm": False,
        }
    )
    phases.append(
        {
            "id": "3.5.retry",
            "name": "compact_minimal_edit",
            "changes": 0,
            "llm": False,
            "skipped": True,
        }
    )

    audit_result: dict[str, Any] = {
        "meaning_changed": False,
        "order_changed": False,
        "new_facts_added": False,
        "important_details_removed": False,
        "style_changed": False,
        "approved": True,
        "notes": minimal_notes,
    }
    phases.append(
        {
            "id": "3.6",
            "name": "llm_audit",
            "changes": 0,
            "llm": False,
            "skipped": True,
            "approved": True,
        }
    )

    changes_payload = [change.to_dict() for change in all_changes if change.before != change.after]
    needs_review = any(item.get("budget_status") == "needs_review" for item in changes_payload)
    status = "ok" if not needs_review else "needs_review"

    return {
        "job_id": job_id,
        "stage": "tts_preparation",
        "version": "1.0.0",
        "created_at": utc_now_iso(),
        "status": status,
        "text": current,
        "full_text": current,
        "confidence": 0.92 if status == "ok" else 0.7,
        "trust_level": "auto" if status == "ok" else "needs_user_review",
        "changes": changes_payload,
        "duration_report": changes_payload,
        "audit_result": audit_result,
        "notes": minimal_notes,
        "provider": "rules_only",
        "phases": phases,
        "issues_found": len(changes_payload),
        "changes_applied": [item["reason"] for item in changes_payload],
        "budget_matched": not needs_review,
        "budget_exceeded": needs_review,
    }
