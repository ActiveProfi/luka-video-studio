import { useEffect, useRef, useState } from "react";
import {
  API,
  approveCleanupEdit,
  approveItem,
  AnnotationEditData,
  CaptureData,
  CleanupEditData,
  CleanupSegmentEdit,
  fetchAnnotationEdit,
  fetchCapture,
  fetchCleanupEdit,
  fetchJob,
  fetchJobs,
  fetchPipelineSteps,
  fetchReview,
  fetchSubtitleEdit,
  fetchVoiceoverScriptEdit,
  artifactDownloadUrl,
  keepItem,
  JobInfo,
  mediaUrl,
  mergeStages,
  PipelineStage,
  PipelineStepTemplate,
  reopenAnnotationEdit,
  reopenCleanupText,
  rerunStage,
  executeStage,
  ReviewItem,
  runPipeline,
  saveCleanupEdit,
  improveCleanupFullText,
  fitCleanupSpeechScriptTiming,
  StageAction,
  SubtitleEditData,
  VoiceoverScriptEditData,
  uploadVideo,
  useFixtureVideo,
} from "./api";
import SubtitleCaptureEditor from "./SubtitleCaptureEditor";
import { SubtitleLayoutEditor } from "./SubtitleLayoutEditor";
import { TimedTextSegmentEditor } from "./TimedTextSegmentEditor";
import { VoiceoverScriptDualEditor } from "./VoiceoverScriptDualEditor";
import { countTimingSteps } from "./timingSteps";
import { defaultLessonOptions, ExistingLessonOptions, LessonOptionsEditor } from "./LessonOptionsEditor";
import StudioHome, { StudioIcon, StudioNav, StudioView } from "./StudioHome";
import ShortVideoStudio, { ApprovalButton } from "./ShortVideoStudio";
import { AnnotationCoordinateEditor } from "./AnnotationCoordinateEditor";

function formatTime(sec: number) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function stageBadgeLabel(status: PipelineStage["status"]) {
  if (status === "completed") return "Готово";
  if (status === "running") return "В обработке";
  if (status === "needs_review") return "Проверьте";
  if (status === "current") return "Следующий";
  return "Ожидает";
}

function CleanupTextEditor({
  jobId,
  data,
  onUpdate,
  onInfo,
  onError,
  embedded = false,
}: {
  jobId: string;
  data: CleanupEditData;
  onUpdate: (stages?: PipelineStage[], saved?: CleanupEditData) => void;
  onInfo: (msg: string) => void;
  onError: (msg: string) => void;
  embedded?: boolean;
}) {
  const duration = data.duration_seconds ?? data.segments[data.segments.length - 1]?.end ?? 0;
  const [fullText, setFullText] = useState(data.editor_text ?? data.speech_script_text ?? data.full_text ?? "");
  const fullTextRef = useRef(data.editor_text ?? data.speech_script_text ?? data.full_text ?? "");
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [timingBusy, setTimingBusy] = useState(false);
  const [speechScriptReady, setSpeechScriptReady] = useState(Boolean(data.speech_script_ready ?? data.speech_script_text));
  const [timingFitDone, setTimingFitDone] = useState(Boolean(data.timing_fit_done));
  const [timingFitReport, setTimingFitReport] = useState(data.timing_fit_report ?? null);
  const [prepStatus, setPrepStatus] = useState<"not_ready" | "ok" | "needs_review">(
    (data.prep_status as "not_ready" | "ok" | "needs_review") ?? (data.speech_script_ready ? "ok" : "not_ready"),
  );
  const isComposingRef = useRef(false);
  const dirtyRef = useRef(false);
  const autoPrepRef = useRef(false);
  const autoTimingRef = useRef(false);

  useEffect(() => {
    dirtyRef.current = false;
    autoPrepRef.current = false;
    autoTimingRef.current = false;
  }, [jobId]);

  useEffect(() => {
    if (isComposingRef.current) return;
    // Не затираем ручной ввод при опросе/обновлении данных с сервера.
    if (dirtyRef.current) return;
    const scriptText = data.speech_script_text?.trim();
    const next = scriptText || data.editor_text || data.full_text || "";
    setFullText(next);
    fullTextRef.current = next;
    setSpeechScriptReady(Boolean(scriptText || data.speech_script_ready));
    setTimingFitDone(Boolean(data.timing_fit_done));
    setTimingFitReport(data.timing_fit_report ?? null);
    const status = data.prep_status;
    if (status === "ok" || status === "needs_review" || status === "not_ready") {
      setPrepStatus(status);
    } else {
      setPrepStatus(scriptText || data.speech_script_ready ? "ok" : "not_ready");
    }
  }, [jobId, data.last_saved_at, data.approved_at, data.full_text, data.speech_script_text, data.speech_script_ready, data.editor_text, data.prep_status, data.timing_fit_done, data.timing_fit_report]);

  const virtualSegment: CleanupSegmentEdit = {
    segment_id: "full",
    start: 0,
    end: duration,
    text: fullText,
    original_text: data.full_original_text ?? fullText,
    slot_seconds: duration,
  };
  const budgetSteps = Math.max(1, data.total_budget_steps ?? countTimingSteps(data.full_original_text ?? data.full_text ?? ""));
  const currentSteps = countTimingSteps(fullText);
  const estimatedSpeechSeconds = duration > 0 ? (currentSteps / budgetSteps) * duration : 0;
  const speechDiffSeconds = estimatedSpeechSeconds - duration;
  const timingOk = Math.abs(speechDiffSeconds) <= 0.5;
  const savePayload = () =>
    speechScriptReady || Boolean(data.speech_script_ready)
      ? { speech_script_text: fullTextRef.current }
      : { full_text: fullTextRef.current };

  const handleSave = async () => {
    setSaving(true);
    onError("");
    try {
      const saved = await saveCleanupEdit(jobId, savePayload());
      const next =
        saved.speech_script_text ?? saved.editor_text ?? fullTextRef.current;
      setFullText(next);
      fullTextRef.current = next;
      dirtyRef.current = false;
      setSpeechScriptReady(Boolean(saved.speech_script_ready ?? speechScriptReady ?? true));
      onInfo(
        saved.speech_script_ready || speechScriptReady
          ? "Speech Script сохранён (текст после). Его возьмёт озвучка и монтаж."
          : "Текст сохранён. Теперь подготовьте Speech Script.",
      );
      onUpdate(undefined, saved);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async () => {
    setApproving(true);
    onError("");
    try {
      await saveCleanupEdit(jobId, savePayload());
      const res = await approveCleanupEdit(jobId, savePayload());
      onInfo(res.message ?? "Текст подтверждён. Запускаем озвучку и следующие шаги.");
      onUpdate(res.stages);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка подтверждения");
    } finally {
      setApproving(false);
    }
  };

  const handleAiImprove = async () => {
    setAiBusy(true);
    onError("");
    try {
      const result = await improveCleanupFullText(jobId, fullTextRef.current);
      if (result.error) {
        throw new Error(result.error);
      }
      const nextText = result.full_text ?? result.text;
      setFullText(nextText);
      fullTextRef.current = nextText;
      dirtyRef.current = false;
      setSpeechScriptReady(true);
      setTimingFitDone(false);
      setTimingFitReport(null);
      setPrepStatus(result.status === "needs_review" ? "needs_review" : "ok");
      const issues = result.issues_found ?? 0;
      const changes = result.changes?.length ?? result.changes_applied?.length ?? 0;
      const summary = result.analysis_summary ? ` ${result.analysis_summary}` : "";
      const note = result.notes ? ` ${result.notes}` : "";
      onInfo(
        `Подшаг 3.1 готов: текст подготовлен к озвучке без кардинальной переписки ` +
          `(правок ${changes}${issues ? `, замечаний ${issues}` : ""}).` +
          `${summary}${note} Дальше можно проверить вручную или запустить 3.2.`,
      );
      const refreshed = await fetchCleanupEdit(jobId);
      onUpdate(undefined, refreshed);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка подготовки Speech Script");
    } finally {
      setAiBusy(false);
    }
  };

  const handleTimingFit = async () => {
    setTimingBusy(true);
    onError("");
    try {
      const result = await fitCleanupSpeechScriptTiming(jobId, fullTextRef.current);
      if (result.error) {
        throw new Error(result.error);
      }
      const nextText = result.full_text ?? result.text;
      setFullText(nextText);
      fullTextRef.current = nextText;
      dirtyRef.current = false;
      setSpeechScriptReady(true);
      setTimingFitDone(true);
      setTimingFitReport(result.timing_fit_report ?? null);
      setPrepStatus(result.status === "needs_review" ? "needs_review" : "ok");
      const matched = result.budget_matched
        ? `бюджет соблюдён (${result.improved_steps}/${result.budget_steps} шагов)`
        : `нужна проверка (${result.improved_steps ?? "?"} из ${result.budget_steps} шагов)`;
      onInfo(
        `Подшаг 3.2 готов: ИИ-помощник подогнал Speech Script под тайминг — ${matched}. ` +
          `${result.notes ?? ""} Проверьте текст и сохраните.`,
      );
      const refreshed = await fetchCleanupEdit(jobId);
      onUpdate(undefined, refreshed);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка ИИ-помощника по таймингу");
    } finally {
      setTimingBusy(false);
    }
  };

  useEffect(() => {
    if (data.review_status === "approved") return;
    if (speechScriptReady || aiBusy || autoPrepRef.current) return;
    autoPrepRef.current = true;
    void handleAiImprove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, data.review_status, speechScriptReady]);

  // Подшаг 3.2 не автозапускаем: сначала можно вручную поправить текст после 3.1.

  if (data.review_status === "approved") {
    return null;
  }

  return (
    <div className={`cleanup-editor ${embedded ? "cleanup-editor-embedded" : ""}`}>
      {!embedded && <h3>Подготовка сценария озвучки</h3>}
      <p className="hint">
        Шаг 3.1 готовит текст к озвучке (аббревиатуры, мусор) — без кардинальной переписки.
        Шаг 3.2 подгоняет длину под тайминг (по кнопке). Шаг 3.3 — обычное ручное редактирование:
        можно править любой фрагмент, в том числе «С 2026 годаа н ОС» → «с 2026 года на УСН».
        clean_transcript.json для субтитров не меняется.
      </p>

      <ol className="cleanup-substeps">
        <li className={`cleanup-substep ${speechScriptReady ? "is-done" : aiBusy ? "is-active" : ""}`}>
          <strong>3.1 Подготовка Speech Script</strong>
          <span>
            {aiBusy && !speechScriptReady
              ? "Идёт подготовка…"
              : speechScriptReady
                ? "Готово"
                : "Ожидает"}
          </span>
          {speechScriptReady && (
            <button
              className="btn-secondary btn-inline-substep"
              type="button"
              disabled={aiBusy || timingBusy || saving || approving}
              onClick={() => {
                autoTimingRef.current = false;
                setTimingFitDone(false);
                void handleAiImprove();
              }}
            >
              {aiBusy ? "Переподготовка…" : "Запустить 3.1 заново"}
            </button>
          )}
        </li>
        <li
          className={`cleanup-substep ${
            timingFitDone ? "is-done" : speechScriptReady && timingBusy ? "is-active" : speechScriptReady ? "is-ready" : ""
          }`}
        >
          <strong>3.2 ИИ-помощник по таймингу</strong>
          <span>
            {!speechScriptReady
              ? "Сначала завершите 3.1"
              : timingBusy
                ? "Подгоняем Speech Script ровно под тайминг, сохраняя расшифровки…"
                : timingFitDone
                  ? "Готово — точный тайминг, формат озвучки сохранён"
                  : "Следующий подшаг"}
          </span>
          {speechScriptReady && (
            <button
              className="btn-ai-improve btn-inline-substep"
              type="button"
              disabled={aiBusy || timingBusy || saving || approving}
              onClick={() => void handleTimingFit()}
            >
              {timingBusy
                ? "ИИ подгоняет тайминг…"
                : timingFitDone
                  ? "Подогнать тайминг ещё раз"
                  : "Запустить ИИ-помощника по таймингу"}
            </button>
          )}
        </li>
      </ol>

      {(speechScriptReady || aiBusy || timingBusy) && (
        <p className={prepStatus === "needs_review" || !timingOk ? "timed-text-warn" : "cleanup-done"}>
          Оценка озвучки: {estimatedSpeechSeconds.toFixed(2)} сек · видео: {duration.toFixed(2)} сек · разница{" "}
          {speechDiffSeconds >= 0 ? "+" : ""}
          {speechDiffSeconds.toFixed(2)} сек · {timingOk ? "в пределах бюджета" : "требуется ручная правка"}
          {timingFitReport?.improved_steps != null && timingFitReport?.budget_steps != null
            ? ` · шаги после 3.2: ${timingFitReport.improved_steps}/${timingFitReport.budget_steps}`
            : ""}
        </p>
      )}
      <div className="cleanup-segment cleanup-segment-full">
        <label htmlFor="cleanup-full-text">
          <span className="transcript-time">0:00–{formatTime(duration)}</span>
              <span className="segment-label">
                {timingFitDone
                  ? "3.3 Ручное редактирование (после подшага 3.2)"
                  : speechScriptReady
                    ? "3.3 Ручное редактирование Speech Script"
                    : "Распознанный текст до подготовки"}
              </span>
        </label>
        <TimedTextSegmentEditor
          segment={virtualSegment}
          textareaId="cleanup-full-text"
          rows={14}
          value={fullText}
          showTimeline={false}
          onCompositionStart={() => {
            isComposingRef.current = true;
          }}
          onCompositionEnd={(nextValue) => {
            isComposingRef.current = false;
            dirtyRef.current = true;
            fullTextRef.current = nextValue;
            setFullText(nextValue);
          }}
          onChange={(nextValue) => {
            dirtyRef.current = true;
            fullTextRef.current = nextValue;
            setFullText(nextValue);
          }}
        />
        {data.full_original_text && data.full_original_text !== fullText && (
          <details className="cleanup-original-details">
            <summary>Исходное распознавание целиком (только для справки)</summary>
            <p className="cleanup-original">{data.full_original_text}</p>
          </details>
        )}
        {data.block_markers && data.block_markers.length > 0 && (
          <details className="cleanup-original-details">
            <summary>Границы блоков озвучки (после сохранения)</summary>
            <ul className="cleanup-block-markers">
              {data.block_markers.map((block, idx) => (
                <li key={block.segment_id}>
                  Блок {idx + 1}: {formatTime(block.start)}–{formatTime(block.end)} · ~
                  {block.budget_steps} шагов
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <div className="cleanup-actions">
        <button
          className="btn-secondary"
          type="button"
          disabled={saving || approving || aiBusy || timingBusy}
          onClick={handleSave}
        >
          {saving ? "Сохранение…" : "Сохранить"}
        </button>
        <button
          className="btn-primary"
          type="button"
          disabled={saving || approving || aiBusy || timingBusy || !speechScriptReady}
          onClick={handleApprove}
        >
          {approving ? "Подтверждение…" : "Подтвердить и запустить озвучку"}
        </button>
      </div>
    </div>
  );
}

function StagePreview({ stage }: { stage: PipelineStage }) {
  if (stage.is_stub || stage.preview?.type === "stub") {
    return (
      <div className="stage-preview stub-preview">
        <p className="stage-summary" style={{ color: "#92400e", background: "#fef3c7", padding: 12, borderRadius: 8 }}>
          <strong>Заглушка.</strong> {stage.preview?.summary || stage.description}
        </p>
        {stage.preview?.text_preview && (
          <p className="hint" style={{ marginTop: 8 }}>
            {stage.preview.text_preview}
          </p>
        )}
        {!stage.preview && stage.status === "current" && (
          <p className="hint">Нажмите «Выполнить» — этап отметится как пройденный (логика подключится позже). Старый код не удалён.</p>
        )}
      </div>
    );
  }

  if (!stage.preview) {
    if (stage.status === "running") {
      const runningHint =
        stage.id === "voiceover"
          ? "Идёт озвучка по вашим субтитрам… Страница обновится сама."
          : stage.id === "annotations"
            ? "Подбираю аннотации… Страница обновится сама."
            : stage.id === "upload"
              ? "Анализирую видео и делю на тайм-блоки…"
              : "Идёт обработка… Страница обновляется автоматически.";
      return <p className="stage-summary stage-running">{runningHint}</p>;
    }
    if (stage.status === "current") {
      if (stage.id === "voiceover") {
        return (
          <p className="stage-summary muted-inline">
            Сохраните субтитры на этапе 2 — озвучка запустится сама.
          </p>
        );
      }
      return (
        <p className="stage-summary muted-inline">
          Этап ещё не выполнен. Нажмите кнопку ниже, когда будете готовы.
        </p>
      );
    }
    return <p className="stage-summary muted-inline">Результат появится после выполнения этапа.</p>;
  }

  const url = mediaUrl(stage.preview.url);
  // Версия файла в ссылке: иначе браузер играет старое видео/аудио из кеша
  const cacheTag = `${stage.preview.filename || ""}-${stage.preview.version || ""}`;
  const versionedUrl = cacheTag
    ? `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(cacheTag)}`
    : url;

  if (stage.preview.type === "text") {
    return (
      <div className="stage-preview">
        {stage.preview.summary && <p className="stage-summary">{stage.preview.summary}</p>}
        {stage.preview.text_preview && (
          <pre className="subtitle-preview">{stage.preview.text_preview}</pre>
        )}
        <a className="link" href={url} target="_blank" rel="noreferrer">
          Открыть {stage.preview.filename}
        </a>
      </div>
    );
  }

  if (stage.preview.type === "video") {
    return (
      <div className="stage-preview">
        <video key={versionedUrl} controls src={versionedUrl} poster={stage.preview.poster_url ? mediaUrl(stage.preview.poster_url) : undefined} />
      </div>
    );
  }
  if (stage.preview.type === "audio") {
    return (
      <div className="stage-preview">
        <audio key={versionedUrl} controls src={versionedUrl} />
      </div>
    );
  }

  return (
    <div className="stage-preview">
      {stage.preview.summary && <p className="stage-summary">{stage.preview.summary}</p>}
      {stage.preview.segments && stage.preview.segments.length > 0 && (
        <ul className="transcript-list">
          {stage.preview.segments.map((seg, i) => (
            <li key={i}>
              <span className="transcript-time">
                {formatTime(seg.start)}–{formatTime(seg.end)}
              </span>
              <span className="transcript-text">{seg.text}</span>
            </li>
          ))}
        </ul>
      )}
      <a className="link" href={url} target="_blank" rel="noreferrer">
        Открыть {stage.preview.filename}
      </a>
    </div>
  );
}

function StepsList({
  stages,
  activeStep,
  onToggle,
  onStageAction,
  actionBusy,
  pipelineRunning,
  jobId,
  captureData,
  cleanupEdit,
  cleanupNeedsReview,
  subtitleEdit,
  voiceoverScriptEdit,
  annotationEdit,
  annotationsNeedsReview,
  onCaptureUpdate,
  onCleanupUpdate,
  onSubtitleUpdate,
  onVoiceoverScriptUpdate,
  onAnnotationUpdate,
  onInfo,
  onError,
}: {
  stages: PipelineStage[];
  activeStep: number | null;
  onToggle: (order: number) => void;
  onStageAction: (stageId: string, action: StageAction) => void;
  actionBusy: string | null;
  pipelineRunning: boolean;
  jobId: string | null;
  captureData: CaptureData | null;
  cleanupEdit: CleanupEditData | null;
  cleanupNeedsReview: boolean;
  subtitleEdit: SubtitleEditData | null;
  voiceoverScriptEdit: VoiceoverScriptEditData | null;
  annotationEdit: AnnotationEditData | null;
  annotationsNeedsReview: boolean;
  onCaptureUpdate: (stages?: PipelineStage[]) => void;
  onCleanupUpdate: (stages?: PipelineStage[], saved?: CleanupEditData) => void;
  onSubtitleUpdate: (stages?: PipelineStage[]) => void;
  onVoiceoverScriptUpdate: (stages?: PipelineStage[]) => void;
  onAnnotationUpdate: () => void;
  onInfo: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const statusIcon = (s: PipelineStage["status"]) => {
    if (s === "completed") return "✓";
    if (s === "running") return "…";
    if (s === "needs_review") return "!";
    if (s === "current") return "→";
    return "○";
  };

  if (stages.length === 0) {
    return (
      <div className="steps-empty">
        <p>Загрузка списка этапов…</p>
      </div>
    );
  }

  return (
    <div className="steps-list">
      {stages.map((stage) => {
        const isOpen =
          (stage.id === "annotations" && stage.status === "completed") ||
          activeStep === stage.order ||
          stage.status === "running" ||
          stage.status === "needs_review" ||
          stage.status === "current";
        const showCaptureEditor =
          stage.id === "subtitle_capture" && Boolean(jobId) && Boolean(captureData);
        const showCleanupEditor =
          stage.id === "cleanup" &&
          Boolean(jobId) &&
          Boolean(cleanupEdit) &&
          cleanupNeedsReview;
        const showSubtitleEditor =
          (stage.id === "subtitle_blocks" || stage.id === "subtitles") &&
          Boolean(jobId) &&
          Boolean(subtitleEdit) &&
          (stage.status === "completed" ||
            stage.status === "current" ||
            stage.status === "needs_review");
        const showVoiceoverScriptEditor =
          stage.id === "voiceover_script" &&
          Boolean(jobId) &&
          Boolean(voiceoverScriptEdit) &&
          (stage.status === "completed" ||
            stage.status === "current" ||
            stage.status === "needs_review");
        return (
          <div
            key={stage.id}
            className={`step-item status-${stage.status} ${isOpen ? "expanded" : ""}`}
          >
            <button className="step-header" type="button" onClick={() => onToggle(stage.order)}>
              <span className="step-icon">{statusIcon(stage.status)}</span>
              <span className="step-num">{stage.order + 1}</span>
              <span className="step-title">{stage.title}</span>
              <span className={`step-badge badge-${stage.status}`}>
                {stageBadgeLabel(stage.status)}
              </span>
            </button>
            {isOpen && (
              <div className="step-body">
                <p>{stage.description}</p>
                {stage.id === "voiceover" && stage.status === "completed" && (
                  <p className="stage-summary">
                    ✓ Озвучка готова. Аннотации создаются автоматически на этапе 4.
                  </p>
                )}
                {stage.id === "annotations" && stage.status === "completed" && (
                  <p className="stage-summary">
                    ✓ Аннотации готовы. Готовый ролик можно скачать ниже.
                    {annotationEdit && <> Размещено: {annotationEdit.confirmed_count}.
                      Без выделения оставлено: {annotationEdit.items.filter(item => item.skipped).length}
                      {" "}(объект или совпадение с речью не подтверждены).</>}
                  </p>
                )}
                {stage.notice && <p className="stage-notice">⚠ {stage.notice}</p>}
                {stage.id === "annotations" && annotationEdit && jobId && !pipelineRunning && annotationEdit.review_status !== "approved" ? (
                  <details>
                  <summary>Дополнительная ручная правка (необязательно)</summary>
                  <AnnotationCoordinateEditor
                    jobId={jobId}
                    data={annotationEdit}
                    onUpdate={onAnnotationUpdate}
                    onInfo={onInfo}
                    onError={onError}
                  />
                  </details>
                ) : showCaptureEditor && captureData && jobId ? (
                  <SubtitleCaptureEditor
                    key={`capture-${jobId}-${captureData.block_count}`}
                    pipelineRunning={pipelineRunning}
                    jobId={jobId}
                    data={captureData}
                    onUpdate={onCaptureUpdate}
                    onInfo={onInfo}
                    onError={onError}
                  />
                ) : showCleanupEditor && cleanupEdit && jobId ? (
                  <CleanupTextEditor
                    key={`cleanup-${jobId}-${cleanupEdit.last_saved_at ?? "new"}`}
                    jobId={jobId}
                    data={cleanupEdit}
                    embedded
                    onUpdate={onCleanupUpdate}
                    onInfo={onInfo}
                    onError={onError}
                  />
                ) : showSubtitleEditor && subtitleEdit && jobId ? (
                  <SubtitleLayoutEditor
                    key={`subtitles-${jobId}-${subtitleEdit.last_saved_at ?? "new"}-${subtitleEdit.video_version ?? ""}`}
                    jobId={jobId}
                    data={subtitleEdit}
                    embedded
                    allowFinalVoiceover={stage.id !== "subtitle_blocks"}
                    pipelineRunning={pipelineRunning}
                    onUpdate={onSubtitleUpdate}
                    onInfo={onInfo}
                    onError={onError}
                  />
                ) : showVoiceoverScriptEditor && voiceoverScriptEdit && jobId ? (
                  <VoiceoverScriptDualEditor
                    key={`vo-script-${jobId}-${voiceoverScriptEdit.updated_at ?? "new"}`}
                    jobId={jobId}
                    data={voiceoverScriptEdit}
                    embedded
                    onUpdate={onVoiceoverScriptUpdate}
                    onInfo={onInfo}
                    onError={onError}
                  />
                ) : (
                  <StagePreview stage={stage} />
                )}
                {stage.id === "annotations" && stage.status === "completed" && jobId && (
                  <div className="stage-download">
                    <ApprovalButton url={`${API}/jobs/${jobId}/shorts/lesson-approval`} disabled={pipelineRunning} />
                    <a
                      className="btn-download"
                      href={artifactDownloadUrl(jobId, "final_lesson.mp4")}
                      download={`${jobId}_lesson.mp4`}
                    >
                      Скачать готовый урок (MP4)
                    </a>
                    <p className="hint stage-download-hint">
                      Видео + озвучка + субтитры (как вы настроили) + аннотации.
                    </p>
                  </div>
                )}
                {stage.actions && stage.actions.length > 0 && (
                  <div className="step-actions">
                    {stage.actions.filter(action => action.id !== "reopen_annotations").map((action) => (
                      <button
                        key={`${action.id}-${action.mode ?? "default"}`}
                        type="button"
                        className={
                          action.id === "run" && action.mode === "execute"
                            ? "btn-primary btn-inline-run"
                            : action.id === "run"
                              ? "btn-secondary btn-rerun"
                            : action.id === "reopen_text" ||
                                action.id === "reopen_annotations" ||
                                action.id === "new_upload"
                              ? "btn-secondary"
                              : "btn-rerun"
                        }
                        disabled={
                          Boolean(actionBusy) ||
                          (pipelineRunning && action.id === "run")
                        }
                        onClick={() => onStageAction(stage.id, action)}
                      >
                        {actionBusy === `${stage.id}:${action.id}` ? "Запуск…" : action.label}
                      </button>
                    ))}
                  </div>
                )}
                {stage.id === "edit" &&
                  stage.status === "completed" &&
                  stage.preview?.filename === "edited_video.mp4" &&
                  jobId && (
                    <div className="stage-download">
                    <ApprovalButton url={`${API}/jobs/${jobId}/shorts/lesson-approval`} disabled={pipelineRunning} />
                      <a
                        className="btn-download"
                        href={artifactDownloadUrl(jobId, "edited_video.mp4")}
                        download={`${jobId}_edited_video.mp4`}
                      >
                        Скачать MP4 (промежуточный результат)
                      </a>
                      <p className="hint stage-download-hint">
                        Видео с исходной картинкой и AI-озвучкой, без субтитров и аннотаций.
                      </p>
                    </div>
                  )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ReviewTable({
  jobId,
  items,
  onUpdate,
}: {
  jobId: string;
  items: ReviewItem[];
  onUpdate: () => void;
}) {
  const pending = items.filter((i) => !i.resolved);

  if (items.length === 0) {
    return (
      <div className="card muted">
        Спорных моментов пока нет. Они появятся после этапа «Решения по таймингу».
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Спорные моменты — ваше решение</h2>
      <p className="hint">
        Ожидают решения: <strong>{pending.length}</strong> из {items.length}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>№</th>
              <th>Время</th>
              <th>Описание</th>
              <th>Предложение</th>
              <th>%</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={item.review_id} className={item.resolved ? "row-done" : ""}>
                <td>{idx + 1}</td>
                <td>{item.time_label}</td>
                <td>
                  <div className="cell-main">{item.reason_for_review}</div>
                </td>
                <td>{item.proposed_label}</td>
                <td>{Math.round(item.confidence * 100)}</td>
                <td>
                  {item.resolved ? (
                    <span className="badge-done">Решено ✓</span>
                  ) : (
                    <div className="row-actions">
                      <button
                        className="btn-approve"
                        onClick={async () => {
                          await approveItem(jobId, item.review_id);
                          onUpdate();
                        }}
                      >
                        Утвердить
                      </button>
                      <button
                        className="btn-keep"
                        onClick={async () => {
                          await keepItem(jobId, item.review_id);
                          onUpdate();
                        }}
                      >
                        Оставить как есть
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatMb(bytes: number) {
  return (bytes / (1024 * 1024)).toFixed(1);
}

export default function App() {
  const [view, setView] = useState<StudioView>(() => {
    const params = new URLSearchParams(location.search);
    const page = params.get("view");
    return page && ["home", "projects", "promotion", "new"].includes(page) ? page as StudioView : params.has("job") ? "workspace" : "home";
  });
  const [jobsLoading, setJobsLoading] = useState(true);
  const [studioQuery, setStudioQuery] = useState("");
  const navigateStudio = (next: StudioView) => {
    setView(next);
    const address = new URL(location.href);
    if (next === "workspace" && jobId) address.searchParams.set("job", jobId);
    else address.searchParams.delete("job");
    if (next === "workspace" || next === "home") address.searchParams.delete("view");
    else address.searchParams.set("view", next);
    address.hash = "";
    window.history.pushState(null, "", address);
    if (next === "home" || next === "projects" || next === "promotion") {
      void fetchJobs().then(setJobs).catch(() => setError("Не удалось обновить проекты. Проверьте соединение со студией."));
    }
    window.scrollTo({top:0, behavior:"instant"});
  };
  const openProject = (id: string, promo = false) => {
    setVideoFile(null);
    setRefFile(null);
    setError("");
    setInfo("");
    setView("workspace");
    setJobId(id);
    const address = new URL(location.href); address.searchParams.set("job", id); address.searchParams.delete("view"); address.hash = "";
    window.history.pushState(null, "", address);
    if (promo) setTimeout(() => document.getElementById("studio-promotion")?.scrollIntoView({behavior:"smooth"}), 150);
    else window.scrollTo({top:0, behavior:"instant"});
  };
  useEffect(() => {
    const onPop = () => {
      const params = new URLSearchParams(location.search);
      const id = params.get("job");
      const page = params.get("view");
      if (id) { setJobId(id); setView("workspace"); }
      else setView(page && ["home", "projects", "promotion", "new"].includes(page) ? page as StudioView : "home");
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const step1Ref = useRef<HTMLElement>(null);
  const step2Ref = useRef<HTMLElement>(null);
  const autoJobSelected = useRef(false);
  const jobSnapshot = useRef("");
  const pipelineError = useRef("");
  const [stepTemplates, setStepTemplates] = useState<PipelineStepTemplate[]>([]);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
  const [jobId, setJobId] = useState("");
  const [jobStages, setJobStages] = useState<PipelineStage[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState("");
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [refFile, setRefFile] = useState<File | null>(null);
  const [lessonOptions, setLessonOptions] = useState(defaultLessonOptions);
  const [companyLogo, setCompanyLogo] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [captureData, setCaptureData] = useState<CaptureData | null>(null);
  const [cleanupEdit, setCleanupEdit] = useState<CleanupEditData | null>(null);
  const [annotationEdit, setAnnotationEdit] = useState<AnnotationEditData | null>(null);
  const [subtitleEdit, setSubtitleEdit] = useState<SubtitleEditData | null>(null);
  const [voiceoverScriptEdit, setVoiceoverScriptEdit] = useState<VoiceoverScriptEditData | null>(null);
  const [stageActionBusy, setStageActionBusy] = useState<string | null>(null);

  const displayStages = mergeStages(stepTemplates, jobStages);
  const sttStage = displayStages.find((s) => s.id === "stt");
  const cleanupStage = displayStages.find((s) => s.id === "cleanup");
  const editStage = displayStages.find((s) => s.id === "edit");
  const ttsStage = displayStages.find((s) => s.id === "tts");
  const subtitlesStage = displayStages.find((s) => s.id === "subtitles");
  const annotationsStage = displayStages.find((s) => s.id === "annotations");
  const cleanupNeedsReview =
    cleanupStage?.status === "needs_review" ||
    cleanupStage?.status === "current" ||
    (cleanupEdit?.review_status === "pending" && Boolean(cleanupEdit));
  const annotationsNeedsReview = annotationsStage?.status === "needs_review";
  const pipelineRunning =
    pipelineStatus === "running" ||
    displayStages.some((s) => s.status === "running");
  const pipelineNeedsRun =
    (sttStage?.status === "current" ||
      sttStage?.status === "running" ||
      cleanupStage?.status === "current" ||
      cleanupStage?.status === "running") &&
    !cleanupNeedsReview;

  const runButtonLabel = () => {
    if (cleanupStage?.status === "running") return "Подготовка сценария…";
    if (sttStage?.status === "running") return "Распознавание…";
    if (cleanupStage?.status === "current") return "Подготовить сценарий озвучки";
    if (sttStage?.status === "current") return "Запустить распознавание речи";
    return "Запустить обработку";
  };

  const applyJobStages = (stages: PipelineStage[], state?: Record<string, unknown>) => {
    jobSnapshot.current = JSON.stringify([stages, state]);
    setJobStages(stages);
    if (state?.status) setPipelineStatus(String(state.status));
    if (state?.status === "failed") {
      setInfo("");
      pipelineError.current = String(state.error || "Обработка остановлена. Повторите текущий этап.");
      setError(pipelineError.current);
    } else if (state?.status && pipelineError.current) {
      const previousError = pipelineError.current;
      setError(current => current === previousError ? "" : current);
      pipelineError.current = "";
    }
    const focus =
      stages.find((s) => s.status === "running") ??
      stages.find((s) => s.status === "current") ??
      [...stages]
        .filter((s) => s.status === "needs_review")
        .sort((a, b) => a.order - b.order)[0] ??
      stages.find((s) => s.status === "completed" && s.id === "stt");
    setActiveStep(previous => focus?.order ?? previous ?? stages[stages.length - 1]?.order ?? 0);
  };

  const loadCapture = async (id: string, stages: PipelineStage[]) => {
    const upload = stages.find((s) => s.id === "upload");
    const capture = stages.find((s) => s.id === "subtitle_capture");
    if (upload?.status !== "completed" || !capture) {
      setCaptureData(null);
      return;
    }
    try {
      setCaptureData(await fetchCapture(id));
    } catch {
      setCaptureData(null);
    }
  };

  const loadCleanupEdit = async (id: string, stages: PipelineStage[]) => {
    const cleanup = stages.find((s) => s.id === "cleanup");
    const mayEdit =
      cleanup?.status === "needs_review" ||
      cleanup?.status === "current" ||
      cleanup?.status === "running";
    if (!mayEdit) {
      setCleanupEdit(null);
      return;
    }
    try {
      const data = await fetchCleanupEdit(id);
      if (data.review_status !== "approved") {
        setCleanupEdit(data);
      } else {
        setCleanupEdit(null);
      }
    } catch {
      setCleanupEdit(null);
    }
  };

  const loadAnnotationEdit = async (id: string, stages: PipelineStage[]) => {
    const annotations = stages.find((s) => s.id === "annotations");
    const voiceover = stages.find((s) => s.id === "voiceover");
    const capture = stages.find((s) => s.id === "subtitle_capture");
    const readyBefore =
      voiceover?.status === "completed" || capture?.status === "completed";
    if (
      readyBefore &&
      annotations &&
      (annotations.status === "needs_review" ||
        annotations.status === "completed" ||
        annotations.status === "running" ||
        annotations.status === "current")
    ) {
      try {
        setAnnotationEdit(await fetchAnnotationEdit(id));
      } catch {
        setAnnotationEdit(null);
      }
    } else {
      setAnnotationEdit(null);
    }
  };

  const loadSubtitleEdit = async (id: string, stages: PipelineStage[]) => {
    const subtitleBlocks = stages.find((s) => s.id === "subtitle_blocks");
    const subtitles = stages.find((s) => s.id === "subtitles");
    const stage = subtitleBlocks ?? subtitles;
    if (
      stage &&
      (stage.status === "completed" ||
        stage.status === "current" ||
        stage.status === "needs_review")
    ) {
      try {
        setSubtitleEdit(await fetchSubtitleEdit(id));
      } catch {
        setSubtitleEdit(null);
      }
    } else {
      setSubtitleEdit(null);
    }
  };

  const loadVoiceoverScriptEdit = async (id: string, stages: PipelineStage[]) => {
    const voiceoverScript = stages.find((s) => s.id === "voiceover_script");
    if (
      voiceoverScript &&
      (voiceoverScript.status === "completed" ||
        voiceoverScript.status === "current" ||
        voiceoverScript.status === "needs_review")
    ) {
      try {
        setVoiceoverScriptEdit(await fetchVoiceoverScriptEdit(id));
      } catch {
        setVoiceoverScriptEdit(null);
      }
    } else {
      setVoiceoverScriptEdit(null);
    }
  };

  const loadJob = async (id: string) => {
    const job = await fetchJob(id);
    applyJobStages(job.stages, job.state);
    await loadCapture(id, job.stages);
    await loadAnnotationEdit(id, job.stages);
    const review = await fetchReview(id);
    setReviewItems(review.items ?? []);
    // Пока субтитры не сохранены — держим открытым основной экран
    const capture = job.stages.find((s) => s.id === "subtitle_capture");
    if (capture && capture.status !== "completed") {
      setActiveStep(capture.order);
    }
  };

  const afterJobReady = async (id: string, message: string, stages: PipelineStage[]) => {
    setView("workspace");
    setJobId(id);
    setVideoFile(null);
    setRefFile(null);
    setCompanyLogo(null);
    applyJobStages(stages);
    setInfo(message);
    const list = await fetchJobs();
    setJobs(list);
    await loadJob(id);
    setTimeout(() => {
      step2Ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 300);
  };

  useEffect(() => {
    fetchPipelineSteps()
      .then(setStepTemplates)
      .catch(() => setError("Не удалось загрузить этапы. Запустите API (порт 8000)."));

    fetchJobs()
      .then((list) => {
        setJobs(list);
        if (!autoJobSelected.current && list.length > 0) {
          autoJobSelected.current = true;
          const requested = new URLSearchParams(window.location.search).get("job");
          if (requested && list.some(j => j.job_id === requested)) setJobId(requested);
          else if (requested) setView("home");
        }
      })
      .catch(() => setError("Не удалось подключиться к студии. Проверьте, что приложение запущено, и обновите страницу."))
      .finally(() => setJobsLoading(false));
  }, []);

  useEffect(() => {
    if (jobId) {
      localStorage.setItem("activeLessonId", jobId);
      const address = new URL(window.location.href); address.searchParams.set("job", jobId); address.searchParams.delete("view");
      window.history.replaceState(null, "", address);
      loadJob(jobId).catch((e) => setError(e.message));
    } else {
      setJobStages([]);
      setReviewItems([]);
      setCaptureData(null);
      setCleanupEdit(null);
      setAnnotationEdit(null);
      setSubtitleEdit(null);
      setVoiceoverScriptEdit(null);
      setPipelineStatus("");
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let fetching = false;
    const interval = setInterval(async () => {
      if (fetching) return;
      fetching = true;
      try {
        const job = await fetchJob(jobId);
        if (cancelled || JSON.stringify([job.stages, job.state]) === jobSnapshot.current) return;
        applyJobStages(job.stages, job.state);
        // Watch idle/failed jobs too: another tab or the API can resume them.
        // Reload editors only on a server-state change, preserving local edits
        // via the capture editor's dirtyRef.
        const capture = await fetchCapture(jobId).catch(() => null);
        if (cancelled) return;
        setCaptureData(capture);
        const annotations = await fetchAnnotationEdit(jobId).catch(() => null);
        if (cancelled) return;
        setAnnotationEdit(annotations);
      } catch {
        /* ignore poll errors */
      } finally {
        fetching = false;
      }
    }, 3000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [jobId]);

  const handleUpload = async () => {
    if (!videoFile) {
      setError("Сначала выберите видеофайл, затем нажмите «Загрузить и начать».");
      return;
    }
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const res = await uploadVideo(videoFile, refFile, setLoadingMsg, lessonOptions, companyLogo);
      await afterJobReady(
        res.job_id,
        res.message ?? `Видео загружено (${res.job_id}). Смотрите Шаг 2 ниже.`,
        res.stages,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  };

  const handleFixture = async () => {
    setLoading(true);
    setError("");
    setInfo("");
    setLoadingMsg("Подключаем тестовое видео из проекта…");
    try {
      const res = await useFixtureVideo();
      await afterJobReady(res.job_id, res.message ?? "Тестовое видео подключено.", res.stages);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  };

  const handleRun = async () => {
    if (!jobId) return;
    setRunning(true);
    setError("");
    try {
      const res = await runPipeline(jobId);
      setInfo(res.message ?? "Обработка запущена");
      await loadJob(jobId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setRunning(false);
    }
  };

  const handleStageAction = async (stageId: string, action: StageAction) => {
    if (!jobId) return;
    const busyKey = `${stageId}:${action.id}`;
    setStageActionBusy(busyKey);
    setError("");
    try {
      if (action.id === "reopen_text") {
        const res = await reopenCleanupText(jobId);
        setInfo(res.message ?? "Текст снова доступен для правки");
        applyJobStages(res.stages);
        setCleanupEdit(res.cleanup);
        setActiveStep(displayStages.find((s) => s.id === "cleanup")?.order ?? 2);
      } else if (action.id === "reopen_annotations") {
        const res = await reopenAnnotationEdit(jobId);
        setInfo(res.message ?? "Аннотации снова доступны для проверки");
        applyJobStages(res.stages);
        setAnnotationEdit(res.annotations);
        setActiveStep(displayStages.find((s) => s.id === "annotations")?.order ?? 6);
      } else if (action.id === "new_upload") {
        setVideoFile(null);
        setRefFile(null);
        setInfo("Выберите исходное видео в начале страницы и нажмите «Загрузить и начать».");
        setTimeout(() => {
          step1Ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 100);
      } else if (action.id === "run") {
        const res =
          action.mode === "rerun"
            ? await rerunStage(jobId, stageId)
            : await executeStage(jobId, stageId);
        setInfo(res.message ?? (action.mode === "rerun" ? "Этап запущен заново" : "Этап запущен"));
        applyJobStages(res.stages, { status: "running" });
        if (action.mode === "rerun" && (stageId === "cleanup" || stageId === "stt")) {
          setCleanupEdit(null);
        }
        if (action.mode === "rerun" && stageId === "annotations") {
          setAnnotationEdit(null);
        }
        await loadJob(jobId);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setStageActionBusy(null);
    }
  };

  const selectedJob = jobs.find((j) => j.job_id === jobId);

  return (
    <div className="studio-shell">
      <StudioNav view={view} onNavigate={navigateStudio}/>
      <main className="studio-main">
      <div className="studio-topbar">
        <span className="studio-topbar-title">{view === "home" ? "Главная" : view === "projects" ? "Мои видео" : view === "promotion" ? "Продвижение" : view === "new" ? "Новый видеоурок" : "Редактор проекта"}</span>
        <label className="studio-global-search"><StudioIcon name="search"/><input type="search" aria-label="Поиск по проектам" placeholder="Найти видеоурок…" value={studioQuery} onChange={event => { setStudioQuery(event.target.value); if (view !== "projects") navigateStudio("projects"); }}/></label>
        <button className="studio-top-create" onClick={() => navigateStudio("new")}><StudioIcon name="plus"/><span>Создать урок</span></button>
      </div>
      <div className="app">
      {loading && (
        <div className="loading-overlay">
          <div className="loading-box">
            <div className="spinner" />
            <p>{loadingMsg || "Загрузка…"}</p>
          </div>
        </div>
      )}

      {(view === "home" || view === "projects" || view === "promotion") && <StudioHome key={view} view={view} jobs={jobs} busy={jobsLoading} query={studioQuery} onQueryChange={setStudioQuery} onNavigate={navigateStudio} onOpen={openProject}/>}
      <div hidden={view !== "workspace" && view !== "new"} className="studio-workspace">
      <header className="workspace-heading">
        <button className="text-action" onClick={()=>navigateStudio("projects")}>← К проектам</button>
        <h1>{view === "new" ? "Новый видеоурок" : selectedJob?.display_name || "Ваш видеоурок"}</h1>
        <p className="subtitle">{view === "new" ? "Загрузите запись экрана с объяснением. Настройте оформление и голос перед запуском." : "От исходной записи до готового урока и роликов для продвижения."}</p>
        {view === "workspace" && jobId && <nav className="workspace-jumps" aria-label="Этапы проекта"><a href="#step-1">Исходник</a><a href="#studio-branding">Оформление</a><a href="#step-2">Видеоурок</a><a href="#studio-promotion">Продвижение</a></nav>}
      </header>

      <section className="card" ref={step1Ref} id="step-1" key={`upload-${jobId}`}>
            <h2>Загрузка исходного видео</h2>

            <p className="hint">
              Запись урока, разбор задания или обзор программы. После выбора файла настройте оформление ниже и запустите обработку.
            </p>

            <div className="upload-grid">
              <label className="upload-box">
                <span className="upload-label">Исходное видео *</span>
                <input
                  type="file"
                  accept="video/mp4,video/quicktime,video/webm,video/*"
                  onChange={(e) => {
                    setVideoFile(e.target.files?.[0] ?? null);
                    setError("");
                  }}
                />
                {videoFile && (
                  <span className="file-name">
                    ✓ {videoFile.name} ({formatMb(videoFile.size)} МБ) — нажмите «Загрузить и начать»
                  </span>
                )}
              </label>

              <details className="upload-extra"><summary>Добавить образец готового урока</summary><label className="upload-box optional">
                <span className="upload-label">Образец готового урока (необязательно)</span>
                <input
                  type="file"
                  accept="video/mp4,video/*"
                  onChange={(e) => setRefFile(e.target.files?.[0] ?? null)}
                />
                {refFile && <span className="file-name">{refFile.name}</span>}
              </label></details>
            </div>

            <div className="actions-row">
              <button className="btn-primary" disabled={loading || !videoFile} onClick={handleUpload}>
                Загрузить и начать
              </button>
              <details className="upload-extra"><summary>Тестовый пример</summary><button className="btn-secondary" disabled={loading} onClick={handleFixture} type="button">Открыть видео из проекта</button></details>
            </div>

      </section>

      <div id="studio-branding">{jobId && !videoFile && view !== "new" ? <ExistingLessonOptions key={jobId} jobId={jobId} busy={loading || pipelineRunning}
        onUpdate={() => void loadJob(jobId)} onInfo={setInfo} onError={setError} /> : <section className="card brand-editor">
        <h2>Оформление {videoFile || view === "new" ? "нового" : "текущего"} видео</h2>
        <LessonOptionsEditor value={lessonOptions} onChange={setLessonOptions} disabled={loading} logoFile={companyLogo} onLogoChange={setCompanyLogo} />
      </section>}</div>
      {view === "new" && <>
        <section className="card" id="step-2">
          <h2>Этапы урока ({stepTemplates.length || 4})</h2>
          <p className="hint">После загрузки записи здесь появится ход обработки вашего урока.</p>
          <div className="steps-list">{stepTemplates.map(stage => <div key={stage.id} className="step-item status-pending">
            <div className="step-header"><span className="step-icon">○</span><span className="step-num">{stage.order + 1}</span><span className="step-title">{stage.title}</span><span className="step-badge badge-pending">Ожидает</span></div>
          </div>)}</div>
        </section>
        <section className="card"><h2>Готовый видеоурок</h2><p className="hint">После обработки здесь можно будет посмотреть, утвердить и скачать урок. Он останется в проекте вместе с короткими роликами.</p></section>
      </>}
      <div hidden={view === "new"}>
      <section className="card" ref={step2Ref} id={view === "new" ? undefined : "step-2"}>
        <div className="section-head">
          <div>
            <h2>Этапы урока ({displayStages.length})</h2>
            {jobId ? (
              <p className="hint job-hint">
                Урок: <strong>{selectedJob?.display_name ?? jobId}</strong>
                {selectedJob?.has_voiceover && (
                  <span className="tag-ok"> · Озвучка готова</span>
                )}
                {selectedJob?.has_annotations && (
                  <span className="tag-ok"> · Аннотации подтверждены</span>
                )}
                {selectedJob?.has_assembly && (
                  <span className="tag-ok"> · Ролик собран</span>
                )}
                {pipelineStatus === "running" && (
                  <span className="tag-run"> · идёт обработка</span>
                )}
              </p>
            ) : (
              <p className="hint job-hint">
                Выберите или загрузите урок — статусы обновятся автоматически.
              </p>
            )}
          </div>
          {jobId && pipelineNeedsRun && (
            <button className="btn-primary" disabled={running} onClick={handleRun} type="button">
              {running ? "Запуск…" : runButtonLabel()}
            </button>
          )}
        </div>

        <StepsList
          stages={displayStages}
          activeStep={activeStep}
          onToggle={(order) => {
            setActiveStep(activeStep === order ? null : order);
            const stage = displayStages.find((s) => s.order === order);
            if (stage?.id === "cleanup" && jobId) {
              void fetchCleanupEdit(jobId)
                .then((data) => {
                  if (data.review_status !== "approved") setCleanupEdit(data);
                })
                .catch(() => undefined);
            }
          }}
          onStageAction={handleStageAction}
          actionBusy={stageActionBusy}
          pipelineRunning={pipelineRunning}
          jobId={jobId}
          captureData={captureData}
          cleanupEdit={cleanupEdit}
          cleanupNeedsReview={cleanupNeedsReview}
          subtitleEdit={subtitleEdit}
          voiceoverScriptEdit={voiceoverScriptEdit}
          annotationEdit={annotationEdit}
          annotationsNeedsReview={annotationsNeedsReview}
          onCaptureUpdate={(stages) => {
            if (stages) {
              applyJobStages(stages);
              const voiceover = stages.find((s) => s.id === "voiceover");
              if (voiceover && (voiceover.status === "running" || voiceover.status === "current")) {
                setActiveStep(voiceover.order);
              }
            }
            if (jobId) {
              void fetchCapture(jobId).then(setCaptureData).catch(() => undefined);
              void loadJob(jobId);
            }
          }}
          onCleanupUpdate={(stages, saved) => {
            if (saved) {
              setCleanupEdit(saved);
            }
            if (stages) applyJobStages(stages, { status: "running" });
            else if (!saved) void loadJob(jobId!);
          }}
          onSubtitleUpdate={(stages) => {
            if (stages) applyJobStages(stages, { status: "running" });
            else void loadJob(jobId!);
            if (jobId) void loadSubtitleEdit(jobId, stages ?? jobStages);
          }}
          onVoiceoverScriptUpdate={(stages) => {
            if (stages) applyJobStages(stages);
            else void loadJob(jobId!);
            if (jobId) void loadVoiceoverScriptEdit(jobId, stages ?? jobStages);
          }}
          onAnnotationUpdate={() => loadJob(jobId!)}
          onInfo={setInfo}
          onError={setError}
        />
      </section>

      </div>
      <div id="studio-promotion"><ShortVideoStudio key={view === "new" ? "shorts-new" : `shorts-${jobId}`} jobId={view === "new" ? "" : jobId} ready={view !== "new" && !!jobId && displayStages.some(s=>s.id === "annotations" && s.status === "completed")} pipelineRunning={view !== "new" && pipelineRunning} /></div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {info && !error && pipelineStatus !== "failed" && <div className="alert alert-success">{info}</div>}

      {view === "workspace" && reviewItems.length > 0 && (
        <section id="step-3">
          <h2 className="section-title">Согласование спорных моментов</h2>
          {jobId ? (
            <ReviewTable jobId={jobId} items={reviewItems} onUpdate={() => loadJob(jobId)} />
          ) : (
            <div className="card muted">Выберите урок выше — здесь появится таблица согласований.</div>
          )}
        </section>
      )}
    </div>
    </main>
    </div>
  );
}
