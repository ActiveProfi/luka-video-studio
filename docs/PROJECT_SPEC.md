# Проект: Автоматизация производства видеоуроков по 1С

## Роль агента
Ты — senior AI engineer / solution architect / backend automation developer / ML systems engineer.
Твоя задача — спроектировать и реализовать production-ready или near-production pipeline, который автоматически превращает один сырой файл `raw_video.mp4` в полностью готовый видеоурок `final_lesson.mp4`.

Ты обязан:
1. Сначала строить план.
2. Затем проектировать контракты данных.
3. Затем реализовывать этапы по одному.
4. После каждого этапа проверять критерии успеха.
5. Не переходить дальше, если текущий этап невалиден.
6. Все межэтапные передачи делать через строгие JSON-артефакты, а не через свободный текст.

---

# Бизнес-контекст

Я создаю короткие онлайн-интенсивы для бухгалтеров по сложным и узким вопросам учета, в основном по НДС.
Каждый интенсив состоит максимум из 3 уроков.
К каждому уроку обязательно прилагается видеоинструкция по работе в 1С.

Особенности домена:
- темы узкие и нестандартные;
- релизы 1С регулярно меняются;
- заранее создать библиотеку типовых сценариев для всех уроков нецелесообразно;
- в будущем источник видео может быть любым, но сервис обработки должен оставаться одинаковым.

Сейчас процесс дорогой, долгий и зависит от Vanessa Automation, специалистов по ней и ручной доработки в CapCut.
Нужно полностью заменить этот процесс автоматизированным конвейером.

---

# Главная цель

## Вход
- `raw_video.mp4`

## Выход
- `final_lesson.mp4`

## Обязательные свойства результата
- очищенное видео без лишних пауз и заминок;
- профессиональная AI-озвучка на русском языке;
- синхронные субтитры;
- рамки, стрелки, выделения;
- вступление и концовка;
- отсутствие необходимости ручного монтажа.

---

# Ключевой архитектурный принцип

Нельзя просто удалить паузы из текста или аудио, а затем наложить новую озвучку на исходное видео.
Это приведет к рассинхрону между действиями на экране и речью.
Поэтому система должна управлять не только текстом, но и временной структурой урока.

## Обязательное правило
После этапа очистки речи должен существовать отдельный узел принятия решений по таймингу:
- какие интервалы можно удалить полностью;
- какие интервалы нужно сократить частично;
- какие интервалы нужно ускорить;
- какие нельзя трогать;
- какие нужно отправить на согласование человеку.

Этот узел называется `Timing Decision Agent`.

---

# Общие правила работы агента

## Базовые правила
- Всегда начинай с Plan Mode.
- Создавай файл плана в `.cursor/plans/`.
- Все изменения делай модульно.
- Сначала проектируй интерфейсы.
- Потом реализуй провайдеры.
- Потом реализуй orchestrator.
- Не делай монолитный скрипт "на всё".
- Не делай хрупкие неявные зависимости между модулями.
- Не передавай важные решения между этапами в текстовом виде; только через схемы и JSON.
- Перед установкой новой библиотеки проверь, нужна ли она действительно.
- Перед завершением этапа запусти тесты, линтер, smoke-run.

## Правила принятия решений
Если видишь неоднозначность:
- сформулируй варианты;
- опиши компромиссы;
- выбери один вариант и поясни почему.

Если есть высокая неопределенность:
- используй human review gate;
- не принимай рискованные решения молча.

---

# Предпочтительный стек

## Backend / orchestration
- Python 3.11+
- FastAPI
- Pydantic
- ffmpeg / ffprobe
- faster-whisper
- openai-whisper как fallback
- pydub
- librosa
- soundfile
- numpy
- scipy
- httpx
- tenacity

## TTS providers
- ElevenLabs
- OpenAI TTS
- Azure Neural Voice

## Subtitle / alignment
- stable-ts или whisperx или другое решение с forced alignment
- выбрать после проверки поддержки русского языка и совместимости

## Quality / tooling
- pytest
- pytest-asyncio
- ruff
- mypy
- pre-commit
- python-dotenv

## Optional UI для human review
- React
- Vite
- TypeScript
- lightweight annotation review UI

---

# Что установить заранее

## Системные зависимости
- FFmpeg
- ffprobe
- Python 3.11+
- Git
- Node.js LTS, если нужен UI
- Docker, если используется контейнеризация

## Python-зависимости
Минимальный предварительный список:
- fastapi
- uvicorn
- pydantic
- faster-whisper
- openai-whisper
- ffmpeg-python
- pydub
- librosa
- soundfile
- numpy
- scipy
- pandas
- httpx
- tenacity
- python-dotenv
- pytest
- pytest-asyncio
- ruff
- mypy
- openai
- elevenlabs
- azure-cognitiveservices-speech

---

# Какие доступы нужны

## Обязательные доступы
- доступ к файловой системе проекта;
- доступ к папке с исходными MP4;
- доступ к папке для промежуточных артефактов и результатов;
- API keys для используемых TTS / STT сервисов;
- доступ к шаблонам заставки, концовки, логотипам;
- доступ к тестовым видео.

## Принцип безопасности
Все доступы должны выдаваться по принципу минимально необходимых прав.
Если используется MCP в Cursor:
- filesystem MCP только к нужным директориям;
- GitHub MCP только если нужен репозиторий;
- browser MCP только если нужен UI smoke test;
- docs/web MCP только для актуальной документации.

---

# Архитектура pipeline

## Верхнеуровневые узлы
1. Input Ingestion Agent
2. Speech Recognition Agent
3. Transcript Normalization Agent
4. Speech Cleanup Agent
5. Timing Decision Agent
6. Video Edit Execution Agent
7. TTS Generation Agent
8. Subtitle Alignment Agent
9. Annotation Suggestion Agent
10. Human Review Gate
11. Video Assembly Agent
12. QA Validation Agent

---

# Структура репозитория

```text
/src
  /domain
    types.py
    contracts.py
    enums.py
    schemas.py

  /pipeline
    /stage0_bootstrap
    /stage1_transcription
    /stage2_cleanup
    /stage2b_timing
    /stage3_editing
    /stage4_tts
    /stage5_subtitles
    /stage6_annotations
    /stage7_assembly
    /stage8_qa

  /agents
    input_ingestion_agent.py
    speech_recognition_agent.py
    transcript_normalization_agent.py
    speech_cleanup_agent.py
    timing_decision_agent.py
    video_edit_execution_agent.py
    tts_generation_agent.py
    subtitle_alignment_agent.py
    annotation_suggestion_agent.py
    qa_validation_agent.py

  /services
    ffmpeg_service.py
    audio_analysis_service.py
    timeline_service.py
    subtitle_service.py
    confidence_service.py

  /providers
    /stt
    /tts
    /alignment

  /review
    review_router.py
    review_queue.py

  /api
    app.py
    routes_jobs.py
    routes_review.py

  /orchestrator
    run_pipeline.py
    pipeline_state.py
    artifact_registry.py

  /schemas
    input_manifest.schema.json
    transcript.schema.json
    clean_transcript.schema.json
    edits_map.schema.json
    timing_decisions.schema.json
    timeline_map.schema.json
    review_bundle.schema.json
    subtitles.schema.json
    annotations.schema.json
    qa_report.schema.json

  /tests
    /unit
    /integration
    /e2e

  /fixtures
  /output
```

---

# Контрактная модель

Каждый агент:
- получает входной JSON или медиа-артефакт;
- валидирует схему;
- генерирует выходной артефакт;
- выставляет confidence и warnings;
- не вызывает напрямую следующий этап без регистрации результата в orchestrator.

Все артефакты должны иметь:
- `job_id`
- `stage`
- `version`
- `created_at`
- `source_artifacts`
- `status`
- `confidence_summary`
- `warnings`
- `errors`

---

# ЭТАП 0. Предпроектная подготовка

## Цель
Подготовить воспроизводимое окружение и базовую архитектуру.

## Что сделать
- создать структуру проекта;
- настроить конфиг;
- создать `.env.example`;
- описать команды запуска;
- сделать базовый orchestrator;
- подключить логирование;
- подключить тесты, линтер, typing;
- сделать docker-сценарий при необходимости;
- создать test fixture `raw_video.mp4`;
- подготовить JSON schemas.

## Критерии успеха
- проект поднимается на чистой машине;
- pipeline запускается одной командой;
- схема конфигурации понятна;
- тестовый прогон стартует без ручных правок.

---

# ЭТАП 1. Распознавание речи

## Цель
Извлечь текст и таймкоды из исходного урока.

## Вход
- `raw_video.mp4`

## Выход
- `transcript.json`
- `srt.json`
- optional `raw_audio.wav`

## Требования
- сегменты речи;
- таймкоды;
- word-level timestamps, если возможно;
- confidence;
- язык;
- пригодность для последующей очистки и монтажа.

## Критерии успеха
- транскрипт формируется автоматически;
- таймкоды монотонны;
- JSON валиден;
- нет критических ошибок по ключевым терминам 1С.

---

# ЭТАП 2. Очистка речи

## Цель
Удалить слова-паразиты, самоповторы, заминки, ложные старты и нерелевантные паузы.

## Вход
- `transcript.json`

## Выход
- `clean_transcript.json`
- `edits_map.json`

## Требования
`edits_map.json` должен содержать:
- исходный интервал;
- тип проблемы;
- proposed_action;
- confidence;
- explanation;
- risk_level.

## Критерии успеха
- мусорные вставки удалены;
- смысл урока сохранён;
- edits map пригоден для следующего этапа;
- доменные термины 1С не потеряны.

---

# ЭТАП 2B. Timing Decision Agent

## Главная задача
Определить, что делать с каждым интервалом после очистки речи так, чтобы:
- не возник рассинхрон между речью и картинкой;
- монтаж оставался естественным;
- важные экранные действия не были испорчены;
- человек подключался только в спорных местах.

## Почему этот узел обязателен
Нельзя автоматически удалять все паузы без учета визуального контекста.
В уроках по 1С пауза может быть:
- пустым молчанием;
- движением мыши к элементу;
- ожиданием открытия формы;
- визуально значимым действием без речи.

Если удалить такой участок неправильно, то:
- AI-озвучка опередит экран;
- субтитры уйдут вперед;
- стрелки и рамки будут наложены не вовремя;
- урок станет непонятным.

---

# Архитектура узла Timing Decision

## Внутренние агенты узла

### 1. Pause Candidate Agent
Назначение:
- анализирует transcript и audio/VAD;
- выделяет интервалы-кандидаты для обработки.

### 2. Visual Activity Agent
Назначение:
- анализирует видеоряд на предмет визуально значимых событий;
- определяет, есть ли на интервале:
  - движение курсора;
  - смена окна;
  - появление формы;
  - раскрытие списка;
  - изменение содержимого экрана;
  - загрузка / ожидание / статичный экран.

### 3. Semantic Action Agent
Назначение:
- сопоставляет фразы из cleaned/raw transcript с действиями пользователя;
- определяет, связан ли интервал с важной инструкцией:
  - "нажимаем"
  - "открываем"
  - "переходим"
  - "выбираем"
  - "ставим флажок"
  - "заполняем"
  - "проводим документ"

### 4. Timing Policy Agent
Назначение:
- на основе кандидата, визуальной активности и семантики принимает решение:
  - `remove_audio_video`
  - `trim_soft`
  - `speedup_video`
  - `keep_as_is`
  - `needs_human_review`

### 5. Confidence Scoring Agent
Назначение:
- считает уверенность решения;
- определяет маршрут:
  - auto-approve;
  - review;
  - senior-review.

### 6. Review Bundle Agent
Назначение:
- собирает все спорные интервалы в один human-review пакет;
- готовит контекст для интерфейса согласования.

---

# Поток данных внутри Timing Decision Agent

## Входные артефакты
- `transcript.json`
- `clean_transcript.json`
- `edits_map.json`
- `raw_video.mp4`
- optional `raw_audio.wav`

## Выходные артефакты
- `pause_candidates.json`
- `visual_activity_map.json`
- `semantic_action_map.json`
- `timing_decisions.json`
- `timeline_map.json`
- `review_bundle.json` при необходимости

---

# Детальный процесс Timing Decision Agent

## Шаг 1. Построение кандидатов
`Pause Candidate Agent` должен:
- найти интервалы тишины;
- найти интервалы с filler words;
- найти интервалы самопоправок;
- найти интервалы с повтором фраз;
- найти интервалы, которые были удалены или сокращены на уровне текста.

### Выход
`pause_candidates.json`

### Структура
```json
{
  "job_id": "job_001",
  "stage": "timing_pause_candidates",
  "candidates": [
    {
      "candidate_id": "cand_001",
      "start": 82.12,
      "end": 87.34,
      "duration": 5.22,
      "source": "vad+cleanup",
      "reason": "long_pause",
      "linked_transcript_segments": ["seg_014", "seg_015"]
    }
  ]
}
```

---

## Шаг 2. Анализ визуальной активности
`Visual Activity Agent` должен по каждому кандидату определить:
- статичен ли экран;
- движется ли курсор;
- есть ли click-событие по косвенным признакам;
- меняется ли окно;
- открывается ли форма;
- есть ли animation/load state;
- есть ли zoom-worthy region.

### Выход
`visual_activity_map.json`

### Структура
```json
{
  "job_id": "job_001",
  "stage": "timing_visual_activity",
  "items": [
    {
      "candidate_id": "cand_001",
      "screen_state": "mostly_static",
      "cursor_motion_score": 0.08,
      "ui_change_score": 0.12,
      "visual_event_type": "no_meaningful_change",
      "confidence": 0.91
    }
  ]
}
```

---

## Шаг 3. Семантический анализ действий
`Semantic Action Agent` должен понять:
- связана ли эта пауза с важным действием;
- завершена ли инструкция до паузы;
- идёт ли подготовка к следующему действию;
- нельзя ли удалить паузу без потери обучающей логики.

### Выход
`semantic_action_map.json`

### Структура
```json
{
  "job_id": "job_001",
  "stage": "timing_semantic_action",
  "items": [
    {
      "candidate_id": "cand_001",
      "instruction_relation": "between_actions",
      "related_action_type": "navigation",
      "critical_for_learning": false,
      "domain_terms": ["Создать"],
      "confidence": 0.88
    }
  ]
}
```

---

## Шаг 4. Принятие монтажного решения
`Timing Policy Agent` объединяет:
- pause candidate;
- visual activity;
- semantic action;
- edits_map;
- общие правила монтажа.

### Возможные решения
- `remove_audio_video` — полностью вырезать интервал и из видео, и из аудио;
- `trim_soft` — сократить интервал частично;
- `speedup_video` — ускорить участок видео;
- `keep_as_is` — ничего не менять;
- `needs_human_review` — отправить на согласование.

### Правила принятия решений
- если экран статичен и визуально ничего важного не происходит → `remove_audio_video`;
- если есть длинное ожидание загрузки и визуальный смысл не теряется → `speedup_video`;
- если движение к кнопке или важному полю ещё не завершено → `trim_soft` или `needs_human_review`;
- если интервал привязан к критически важной инструкции → не удалять агрессивно;
- если low confidence → human review.

### Выход
`timing_decisions.json`

### Структура
```json
{
  "job_id": "job_001",
  "stage": "timing_policy",
  "decisions": [
    {
      "candidate_id": "cand_001",
      "decision": "remove_audio_video",
      "target_start": 82.12,
      "target_end": 87.34,
      "confidence": 0.93,
      "risk_level": "low",
      "why": "long pause with no meaningful screen change",
      "requires_review": false
    },
    {
      "candidate_id": "cand_002",
      "decision": "needs_human_review",
      "target_start": 190.20,
      "target_end": 194.60,
      "confidence": 0.61,
      "risk_level": "medium",
      "why": "cursor movement appears linked to upcoming action",
      "requires_review": true
    }
  ]
}
```

---

## Шаг 5. Confidence routing
`Confidence Scoring Agent` обязан маршрутизировать интервалы по порогам.

### Обязательные пороги по умолчанию
- `confidence >= 0.92` → auto-approve
- `0.75 <= confidence < 0.92` → standard human review
- `confidence < 0.75` → required human review
- `confidence < 0.60` и `critical_for_learning = true` → senior review / mandatory approval

Эти пороги должны быть вынесены в config и калиброваться на реальных уроках.

---

## Шаг 6. Human Review Gate
Human Review Gate ставится не на весь этап, а только после `timing_decisions.json` и только для решений с:
- `requires_review = true`;
- low confidence;
- critical_for_learning = true;
- conflicting signals между visual и semantic анализом;
- нетиповым поведением интерфейса.

### Что получает человек
`review_bundle.json`

### Структура
```json
{
  "job_id": "job_001",
  "stage": "timing_review_bundle",
  "items": [
    {
      "review_id": "rev_001",
      "candidate_id": "cand_002",
      "video_excerpt_start": 187.20,
      "video_excerpt_end": 197.60,
      "proposed_decision": "trim_soft",
      "alternative_decisions": [
        "keep_as_is",
        "speedup_video"
      ],
      "confidence": 0.61,
      "reason_for_review": "possible mismatch between cursor movement and speech timing",
      "evidence": {
        "visual_event_type": "cursor_movement",
        "instruction_relation": "pre_action_transition",
        "critical_for_learning": true
      }
    }
  ]
}
```

### Что делает человек
Человек не монтирует ролик вручную.
Человек только подтверждает одно из решений:
- approve proposed;
- choose alternative;
- mark custom trim;
- keep original.

### Результат review gate
`review_resolution.json`

```json
{
  "job_id": "job_001",
  "stage": "timing_review_resolution",
  "resolutions": [
    {
      "review_id": "rev_001",
      "final_decision": "trim_soft",
      "approved_by": "user",
      "custom_parameters": {
        "trim_seconds": 1.5
      }
    }
  ]
}
```

---

## Шаг 7. Финальная временная карта
После auto-approve и human review должен быть создан единый `timeline_map.json`.

### Назначение
Он является источником истины для:
- Video Edit Execution Agent;
- TTS Generation Agent;
- Subtitle Alignment Agent;
- Annotation Suggestion Agent;
- Video Assembly Agent.

### Структура
```json
{
  "job_id": "job_001",
  "stage": "timeline_map",
  "segments": [
    {
      "source_start": 0.0,
      "source_end": 82.12,
      "target_start": 0.0,
      "target_end": 82.12,
      "transform": "keep"
    },
    {
      "source_start": 82.12,
      "source_end": 87.34,
      "target_start": 82.12,
      "target_end": 82.12,
      "transform": "removed"
    },
    {
      "source_start": 190.20,
      "source_end": 194.60,
      "target_start": 185.20,
      "target_end": 187.70,
      "transform": "trim_soft"
    }
  ]
}
```

---

# ЭТАП 3. Video Edit Execution Agent

## Задача
Не "думать", а исполнять уже принятые решения из `timeline_map.json` и `timing_decisions.json`.

## Вход
- `raw_video.mp4`
- `timing_decisions.json`
- `timeline_map.json`
- optional `review_resolution.json`

## Выход
- `edited_video.mp4`

## Правило
Этот агент не принимает новые смысловые решения.
Он только исполняет утвержденную временную карту.

## Критерии успеха
- edited video физически синхронизирован с новой структурой;
- ffprobe проходит;
- нет битых участков;
- нет неожиданных временных скачков;
- итоговая длительность соответствует timeline map.

---

# ЭТАП 4. TTS Generation Agent

## Вход
- `clean_transcript.json`
- `timeline_map.json`

## Выход
- `voiceover.wav`
- `voiceover_segments.json`

## Важно
TTS должен генерироваться уже под финальную временную структуру, а не под исходное видео.
Если segment timing требует микропауз или растяжения, агент должен учитывать timeline constraints.

## Критерии успеха
- озвучка ложится на отредактированное видео;
- русский язык звучит естественно;
- нет заметных швов;
- есть соответствие сегментов voiceover и timeline map.

---

# ЭТАП 5. Subtitle Alignment Agent

## Вход
- `clean_transcript.json`
- `voiceover.wav`
- `timeline_map.json`

## Выход
- `subtitles.srt`
- optional `subtitles.ass`
- `subtitle_timing.json`

## Правило
Субтитры строятся не от исходного тайминга, а от voiceover + timeline map.

## Критерии успеха
- субтитры синхронны с voiceover;
- легко читаются;
- не ломают термины 1С;
- нет пересекающихся интервалов.

---

# ЭТАП 6. Annotation Suggestion Agent

## Вход
- `clean_transcript.json`
- `edited_video.mp4`
- `timeline_map.json`

## Выход
- `annotation_suggestions.json`
- `approved_annotations.json`

## Правило
Все предложения для стрелок, рамок и zoom должны опираться на новую временную карту, а не на исходное видео.

## Критерии успеха
- предложения понятны;
- время наложений не съехало;
- возможен быстрый human approval для спорных аннотаций.

---

# ЭТАП 7. Video Assembly Agent

## Вход
- `edited_video.mp4`
- `voiceover.wav`
- `subtitles.srt` или `subtitles.ass`
- `approved_annotations.json`
- intro/outro assets

## Выход
- `final_lesson.mp4`

## Задача
Собрать итоговый MP4 с финальными дорожками и графикой.

## Критерии успеха
- видео публикуемо без ручной доработки;
- субтитры синхронны;
- озвучка синхронна;
- рамки и стрелки своевременны;
- вступление и концовка вставлены корректно.

---

# ЭТАП 8. QA Validation Agent

## Задача
Проверить весь pipeline перед финальной выдачей.

## Вход
- все промежуточные и итоговые артефакты

## Выход
- `qa_report.json`

## Проверки
- все JSON соответствуют схемам;
- все обязательные артефакты существуют;
- edited_video, voiceover, subtitles и annotations используют одну и ту же timeline logic;
- итоговый MP4 воспроизводится;
- нет явного рассинхрона;
- confidence report сохранен;
- review decisions, если были, применены.

---

# JSON-файлы и передача между агентами

## Основная цепочка
1. `input_manifest.json`
2. `transcript.json`
3. `clean_transcript.json`
4. `edits_map.json`
5. `pause_candidates.json`
6. `visual_activity_map.json`
7. `semantic_action_map.json`
8. `timing_decisions.json`
9. `review_bundle.json` -> optional
10. `review_resolution.json` -> optional
11. `timeline_map.json`
12. `edited_video.mp4`
13. `voiceover.wav`
14. `voiceover_segments.json`
15. `subtitles.srt`
16. `subtitle_timing.json`
17. `annotation_suggestions.json`
18. `approved_annotations.json`
19. `final_lesson.mp4`
20. `qa_report.json`

---

# Где ставить Human Review Gate

## Обязательные human review точки

### Gate 1 — Timing Review Gate
После `timing_decisions.json`, до `timeline_map.json`.
Нужен для спорных решений по монтажу и синхронизации.

### Gate 2 — Annotation Review Gate
После `annotation_suggestions.json`, до `approved_annotations.json`.
Нужен для подтверждения рамок, стрелок, zoom.

## Опциональные human review точки
- после STT, если качество распознавания катастрофически низкое;
- после TTS, если выбранный голос звучит плохо на доменных терминах;
- перед финальной публикацией для sample QA.

---

# Критерии успеха Timing Decision Agent

Этап считается успешным только если:
- все candidate intervals классифицированы;
- для каждого интервала есть решение или review status;
- нет "потерянных" промежутков;
- `timeline_map.json` строится детерминированно;
- downstream этапы могут использовать новую временную шкалу без двусмысленностей;
- доля human review контролируема и снижается по мере накопления правил.

---

# Формат ответа агента после каждого этапа

Каждый крупный ответ должен содержать:

## 1. Что сделано
Список завершённых действий.

## 2. Какие файлы созданы
Файлы, схемы, модули, тесты.

## 3. Как проверить
Команды запуска, команды тестов, пример входа/выхода.

## 4. Пройденные критерии успеха
Что валидировано автоматически.

## 5. Риски и ограничения
Что пока не покрыто.

## 6. Следующий шаг
Следующий конкретный этап.

---

# Что делать сначала

## Первая задача для агента
Сначала:
1. Построй детальный план MVP.
2. Предложи структуру репозитория.
3. Предложи список зависимостей:
   - required
   - optional
   - dev
4. Подготовь `.env.example`
5. Опиши JSON contracts для:
   - transcript
   - edits_map
   - timing_decisions
   - review_bundle
   - timeline_map
6. Опиши пороги confidence routing.
7. Только после этого приступай к реализации ЭТАПА 0.

Не начинай реализацию всех этапов сразу без утверждённого плана.
