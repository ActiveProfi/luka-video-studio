/** Прямой URL API (без прокси Vite — надёжнее на Windows) */
export const API_BASE = "http://127.0.0.1:8000";
export const API = API_BASE;
export const UPLOAD_API = API_BASE;

export type LessonOptions = {
  provider: "yandex" | "openai" | "elevenlabs" | "edge"; voice: string; speed: number; automatic: boolean;
  title: string; intro: boolean; outro: boolean;
  company_name: string; company_description: string;
  topic_context: string; terminology: string; content_profile: "general" | "accounting";
  intro_seconds: number; outro_seconds: number; logo_url?: string | null;
  branding_reference_ids?: string[];
  branding_reference_notes?: string;
};
export type VoiceChoice = {provider: string; id: string; label: string; available: boolean};

export type JobInfo = {
  job_id: string;
  path: string;
  display_name: string;
  stages_done?: number;
  has_transcript?: boolean;
  has_cleanup?: boolean;
  has_cleanup_approved?: boolean;
  has_timing?: boolean;
  has_timing_completed?: boolean;
  has_edited_video?: boolean;
  has_voiceover?: boolean;
  has_subtitles?: boolean;
  has_sync?: boolean;
  has_assembly?: boolean;
  has_annotations?: boolean;
  pipeline_status?: string;
};

export type AnnotationItemPreview = {
  annotation_id: string;
  type: string;
  type_label?: string;
  label: string;
  target_start?: number;
  target_end?: number;
  style?: string;
};

export type AnnotationBlockEdit = {
  block_id: string;
  block_index: number;
  segment_id?: string;
  target_start: number;
  target_end: number;
  text: string;
  annotations: AnnotationItemPreview[];
  user_comment: string;
};

export type SyncBlockEdit = {
  block_id: string;
  block_index: number;
  segment_id?: string;
  target_start: number;
  target_end: number;
  target_slot_seconds?: number;
  audio_start?: number;
  audio_end?: number;
  audio_duration_seconds?: number;
  slot_gap_seconds?: number;
  recommended_offset_seconds?: number;
  offset_adjustment_seconds: number;
  text: string;
  sync_note?: string;
  user_comment: string;
};

export type SyncEditData = {
  job_id: string;
  review_status: "pending" | "approved";
  last_saved_at: string | null;
  approved_at: string | null;
  preview_video_url: string;
  preview_video: string;
  global_audio_offset_seconds: number;
  video_duration_seconds?: number;
  voiceover_duration_seconds?: number;
  blocks: SyncBlockEdit[];
};

export type AnnotationPlacementItem = {
  annotation_id: string;
  target_start: number;
  target_end: number;
  text: string;
  suggested_type: string;
  type_label?: string;
  frame_url: string | null;
  frame_file?: string | null;
  placement_confirmed: boolean;
  skipped: boolean;
  anchor?: { x: number; y: number; width?: number; height?: number } | null;
  arrow_direction?: string;
  arrow_length_ratio?: number;
  reason?: string;
};

export type AnnotationEditData = {
  job_id: string;
  review_status: "pending" | "approved";
  last_saved_at: string | null;
  approved_at: string | null;
  preview_video_url: string;
  preview_video: string;
  studio_video_url?: string;
  studio_video?: string;
  video_version?: string | null;
  video_duration_seconds?: number;
  suggestion_count: number;
  confirmed_count: number;
  pending_count: number;
  items: AnnotationPlacementItem[];
  blocks: AnnotationBlockEdit[];
  subtitle_layout?: SubtitleLayout | null;
  subtitle_cues?: SubtitleCue[];
  studio_has_subtitles?: boolean;
  studio_subtitles_burned?: boolean;
};

export type AnnotationPlacementPayload = {
  type: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  arrow_direction?: string;
  arrow_length_ratio?: number;
  target_start?: number;
  target_end?: number;
  skipped?: boolean;
};

export type AnnotationStudioItem = {
  annotation_id?: string;
  type: string;
  text?: string;
  target_start: number;
  target_end: number;
  x: number;
  y: number;
  width?: number;
  height?: number;
  arrow_direction?: string;
  arrow_length_ratio?: number;
  skipped?: boolean;
};

export type SubtitleCue = {
  cue_id: string;
  source_segment_id?: string;
  start: number;
  end: number;
  text: string;
};

export type SubtitleLayout = {
  x: number;
  y: number;
  width: number;
  height: number;
  font_size_px: number;
  alignment: string;
  font_color: string;
  background_color: string;
  background_opacity: number;
  font_bold: boolean;
  font_italic: boolean;
  cue_layouts?: Record<string, { x: number; y: number; width: number; height: number }>;
};

export type SubtitleFinalVoiceoverStatus = {
  ok: boolean;
  message?: string | null;
  segment_count?: number | null;
  created_at?: string | null;
  warnings?: string[];
};

export type SubtitleEditData = {
  job_id: string;
  video_url: string;
  video_filename: string;
  video_version?: string | null;
  cue_count: number;
  total_duration_seconds: number;
  layout: SubtitleLayout;
  cues: SubtitleCue[];
  last_saved_at: string | null;
  final_voiceover?: SubtitleFinalVoiceoverStatus | null;
};

export type CleanupSegmentEdit = {
  segment_id: string;
  start: number;
  end: number;
  text: string;
  original_text?: string;
  agent_text?: string;
  slot_seconds?: number;
  estimated_speech_seconds?: number;
  timing_margin_seconds?: number;
  exceeds_by_seconds?: number;
  timing_exceeded?: boolean;
};

export type CleanupBlockMarker = {
  segment_id: string;
  start: number;
  end: number;
  budget_steps: number;
};

export type CleanupEditData = {
  job_id: string;
  review_status: "pending" | "approved";
  manual_edits_count: number;
  last_saved_at: string | null;
  approved_at: string | null;
  duration_seconds?: number;
  full_text?: string;
  full_original_text?: string;
  text_before?: string | null;
  speech_script_text?: string | null;
  speech_script_ready?: boolean;
  prep_status?: "not_ready" | "ok" | "needs_review" | string;
  timing_fit_done?: boolean;
  timing_fit_report?: {
    budget_steps?: number;
    improved_steps?: number;
    budget_matched?: boolean;
    budget_exceeded?: boolean;
    attempts?: number;
    notes?: string;
    provider?: string;
    draft_steps?: number;
  } | null;
  editor_text?: string;
  total_budget_steps?: number;
  block_markers?: CleanupBlockMarker[];
  segments: CleanupSegmentEdit[];
};

export type CleanupPreparationChange = {
  before: string;
  after: string;
  stage: string;
  reason: string;
  original_duration_seconds: number;
  edited_duration_seconds: number;
  duration_diff_seconds: number;
  budget_status: "within_budget" | "needs_review" | "not_checked";
  metadata?: Record<string, unknown>;
};

export type CleanupAuditResult = {
  meaning_changed?: boolean;
  order_changed?: boolean;
  new_facts_added?: boolean;
  important_details_removed?: boolean;
  style_changed?: boolean;
  approved?: boolean;
  notes?: string;
};

export type StagePreview = {
  type: string;
  url: string;
  filename: string;
  version?: string | null;
  poster_url?: string;
  summary?: string;
  segments?: { start: number; end: number; text: string }[];
  text_preview?: string;
};

export type StageAction = {
  id: "run" | "reopen_text" | "reopen_sync" | "reopen_annotations" | "new_upload";
  label: string;
  mode?: "execute" | "rerun";
};

export type PipelineStage = {
  id: string;
  order: number;
  title: string;
  description: string;
  status: "completed" | "running" | "current" | "pending" | "needs_review";
  preview: StagePreview | null;
  actions?: StageAction[];
  is_stub?: boolean;
  notice?: string | null;
};

/** Этап 2 (v3): тайм-блок с субтитром, который пишет пользователь */
export type CaptureBlock = {
  id: number;
  start: number;
  end: number;
  subtitle: string;
  status: "empty" | "edited" | "saved" | string;
  needs_review?: boolean;
  review_reason?: string;
};

export type CaptureData = {
  job_id: string;
  video_url: string;
  video_filename: string;
  video_version?: string | null;
  duration_seconds: number;
  fps?: number | null;
  width?: number | null;
  height?: number | null;
  has_audio?: boolean;
  layout: SubtitleLayout;
  blocks: CaptureBlock[];
  block_count: number;
  filled_count: number;
  saved_at?: string | null;
  updated_at?: string | null;
  script_review?: { status: string; review_count?: number; warnings: string[]; segments: {segment_id: string; original_text: string; suggested_text?: string; text: string; needs_review: boolean; review_reason: string; start: number; end: number}[] } | null;
};

export type PipelineStepTemplate = {
  id: string;
  order: number;
  title: string;
  description: string;
};

export type ReviewItem = {
  review_id: string;
  candidate_id: string;
  video_excerpt_start: number;
  video_excerpt_end: number;
  proposed_decision: string;
  proposed_label: string;
  alternative_decisions: string[];
  confidence: number;
  reason_for_review: string;
  context_transcript?: string;
  time_label: string;
  resolved: boolean;
  evidence?: Record<string, unknown>;
};

export type JobDetail = {
  job_id: string;
  stages: PipelineStage[];
  state: Record<string, unknown>;
};

function parseErrorDetail(err: unknown): string {
  if (!err || typeof err !== "object") return "Неизвестная ошибка";
  const d = (err as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? JSON.stringify(x)).join("; ");
  return "Ошибка сервера";
}

export async function fetchJobs(): Promise<JobInfo[]> {
  const r = await fetch(`${API}/jobs`);
  if (!r.ok) throw new Error("API недоступен");
  const d = await r.json();
  return d.jobs ?? [];
}

export async function fetchPipelineSteps(): Promise<PipelineStepTemplate[]> {
  const r = await fetch(`${API}/pipeline/steps`);
  if (!r.ok) throw new Error("Не удалось загрузить список этапов");
  const d = await r.json();
  return d.steps ?? [];
}

/** Выбрать урок с максимальным прогрессом (с готовым STT — в приоритете) */
export function pickBestJob(jobs: JobInfo[]): string {
  if (jobs.length === 0) return "";
  const sorted = [...jobs].sort((a, b) => {
    const pa = a.stages_done ?? 0;
    const pb = b.stages_done ?? 0;
    if (pb !== pa) return pb - pa;
    if (Boolean(b.has_transcript) !== Boolean(a.has_transcript)) {
      return Number(b.has_transcript) - Number(a.has_transcript);
    }
    if (Boolean(b.has_cleanup_approved) !== Boolean(a.has_cleanup_approved)) {
      return Number(b.has_cleanup_approved) - Number(a.has_cleanup_approved);
    }
    if (Boolean(b.has_timing_completed) !== Boolean(a.has_timing_completed)) {
      return Number(b.has_timing_completed) - Number(a.has_timing_completed);
    }
    if (Boolean(b.has_edited_video) !== Boolean(a.has_edited_video)) {
      return Number(b.has_edited_video) - Number(a.has_edited_video);
    }
    if (Boolean(b.has_voiceover) !== Boolean(a.has_voiceover)) {
      return Number(b.has_voiceover) - Number(a.has_voiceover);
    }
    if (Boolean(b.has_subtitles) !== Boolean(a.has_subtitles)) {
      return Number(b.has_subtitles) - Number(a.has_subtitles);
    }
    if (Boolean(b.has_sync) !== Boolean(a.has_sync)) {
      return Number(b.has_sync) - Number(a.has_sync);
    }
    if (Boolean(b.has_assembly) !== Boolean(a.has_assembly)) {
      return Number(b.has_assembly) - Number(a.has_assembly);
    }
    if (Boolean(b.has_annotations) !== Boolean(a.has_annotations)) {
      return Number(b.has_annotations) - Number(a.has_annotations);
    }
    return b.job_id.localeCompare(a.job_id);
  });
  return sorted[0].job_id;
}

/** Шаблон этапов + статус из job (если job ещё не выбран — все «ожидает») */
export function mergeStages(
  templates: PipelineStepTemplate[],
  jobStages: PipelineStage[],
): PipelineStage[] {
  if (templates.length === 0) return jobStages;
  const byId = new Map(jobStages.map((s) => [s.id, s]));
  return templates.map((t) => {
    const fromJob = byId.get(t.id);
    if (fromJob) return fromJob;
    return {
      ...t,
      status: "pending" as const,
      preview: null,
    };
  });
}

export async function uploadVideo(
  video: File,
  reference?: File | null,
  onProgress?: (msg: string) => void,
  options?: LessonOptions,
  companyLogo?: File | null,
): Promise<{ job_id: string; stages: PipelineStage[]; message?: string }> {
  const form = new FormData();
  form.append("video", video);
  if (reference) form.append("reference", reference);
  if (options) form.append("options", JSON.stringify(options));
  if (companyLogo) form.append("company_logo", companyLogo);

  const sizeMb = (video.size / (1024 * 1024)).toFixed(1);
  onProgress?.(`Отправка ${sizeMb} МБ на сервер… Подождите 1–3 минуты.`);

  const r = await fetch(`${UPLOAD_API}/jobs/upload`, { method: "POST", body: form });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function useFixtureVideo(): Promise<{ job_id: string; stages: PipelineStage[]; message?: string }> {
  const r = await fetch(`${API}/jobs/from-fixtures`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function fetchJob(jobId: string): Promise<JobDetail> {
  const r = await fetch(`${API}/jobs/${jobId}`);
  if (!r.ok) throw new Error("Урок не найден");
  return r.json();
}

export async function runPipeline(jobId: string) {
  const r = await fetch(`${API}/jobs/${jobId}/run`, { method: "POST" });
  if (!r.ok) throw new Error("Не удалось запустить обработку");
  return r.json();
}

export async function fetchCleanupEdit(jobId: string): Promise<CleanupEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/edit`);
  if (!r.ok) throw new Error("Не удалось загрузить текст для правки");
  return r.json();
}

export async function saveCleanupEdit(
  jobId: string,
  payload:
    | { full_text: string }
    | { speech_script_text: string }
    | { segments: { segment_id: string; text: string }[] },
): Promise<CleanupEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/edit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export type CleanupAiFullImproveResult = {
  text: string;
  full_text?: string;
  notes?: string;
  provider?: string;
  budget_steps?: number;
  improved_steps?: number;
  budget_matched?: boolean;
  budget_exceeded?: boolean;
  attempts?: number;
  analysis_summary?: string;
  issues_found?: number;
  changes_applied?: string[];
  changes?: CleanupPreparationChange[];
  duration_report?: CleanupPreparationChange[];
  audit_result?: CleanupAuditResult;
  status?: "ok" | "needs_review";
  confidence?: number;
  trust_level?: "auto" | "needs_user_review";
  agent?: string;
  phases?: { id?: string; name?: string; changes?: number; llm?: boolean; approved?: boolean }[];
  error?: string;
};

export async function improveCleanupFullText(
  jobId: string,
  fullText?: string,
): Promise<CleanupAiFullImproveResult> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/improve-full`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fullText ? { full_text: fullText } : {}),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export type CleanupTimingFitResult = CleanupAiFullImproveResult & {
  timing_fit_done?: boolean;
  timing_fit_report?: CleanupEditData["timing_fit_report"];
  substep?: string;
};

export async function fitCleanupSpeechScriptTiming(
  jobId: string,
  fullText?: string,
): Promise<CleanupTimingFitResult> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/fit-timing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fullText ? { full_text: fullText } : {}),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export type CleanupAiImproveResult = {
  segment_id: string;
  text: string;
  notes?: string;
  provider?: string;
  budget_steps?: number;
  improved_steps?: number;
  budget_matched?: boolean;
  budget_exceeded?: boolean;
  attempts?: number;
  error?: string;
};

export async function improveCleanupSegment(
  jobId: string,
  segmentId: string,
): Promise<CleanupAiImproveResult> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/improve/${segmentId}`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function improveAllCleanupSegments(
  jobId: string,
): Promise<{ segments: CleanupAiImproveResult[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/improve-all`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function approveCleanupEdit(
  jobId: string,
  payload:
    | { full_text: string }
    | { speech_script_text: string }
    | { segments: { segment_id: string; text: string }[] }
    | Record<string, never>,
): Promise<{ ok: boolean; message?: string; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function reopenCleanupText(
  jobId: string,
): Promise<{ ok: boolean; message?: string; cleanup: CleanupEditData; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/cleanup/reopen`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function fetchSyncEdit(jobId: string): Promise<SyncEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/sync/edit`);
  if (!r.ok) throw new Error("Не удалось загрузить синхронизацию для проверки");
  return r.json();
}

export async function saveSyncEdit(
  jobId: string,
  blocks: { block_id: string; offset_adjustment_seconds: number; user_comment: string }[],
): Promise<SyncEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/sync/edit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function approveSyncEdit(
  jobId: string,
  blocks: { block_id: string; offset_adjustment_seconds: number; user_comment: string }[],
): Promise<{ ok: boolean; message?: string; sync: SyncEditData; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/sync/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function reopenSyncEdit(
  jobId: string,
): Promise<{ ok: boolean; message?: string; sync: SyncEditData; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/sync/reopen`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function fetchAnnotationEdit(jobId: string): Promise<AnnotationEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/annotations/edit`);
  if (!r.ok) throw new Error("Не удалось загрузить аннотации для проверки");
  const data = await r.json();
  return {
    ...data,
    items: data.items ?? [],
    confirmed_count: data.confirmed_count ?? 0,
    pending_count: data.pending_count ?? 0,
    blocks: data.blocks ?? [],
  };
}

export async function saveAnnotationEdit(
  jobId: string,
  blocks: { block_id: string; user_comment: string }[],
): Promise<AnnotationEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/annotations/edit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function approveAnnotationEdit(
  jobId: string,
  blocks?: { block_id: string; user_comment: string }[],
): Promise<{
  ok: boolean;
  message?: string;
  download_url?: string | null;
  final_ready?: boolean;
  annotations: AnnotationEditData;
  stages: PipelineStage[];
}> {
  const r = await fetch(`${API}/jobs/${jobId}/annotations/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(blocks ? { blocks } : {}),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function reopenAnnotationEdit(
  jobId: string,
): Promise<{ ok: boolean; message?: string; annotations: AnnotationEditData; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/annotations/reopen`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function saveAnnotationPlacement(
  jobId: string,
  annotationId: string,
  placement: AnnotationPlacementPayload,
): Promise<{ ok: boolean; message?: string; annotations: AnnotationEditData }> {
  const r = await fetch(`${API}/jobs/${jobId}/annotations/${encodeURIComponent(annotationId)}/placement`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(placement),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function saveAnnotationStudio(
  jobId: string,
  items: AnnotationStudioItem[],
  replaceAll = true,
): Promise<{ ok: boolean; message?: string; annotations: AnnotationEditData }> {
  const r = await fetch(`${API}/jobs/${jobId}/annotations/studio`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, replace_all: replaceAll, saved_by: "user" }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

// --- Этап 2 (v3): субтитры прямо на видео ---

export async function fetchCapture(jobId: string): Promise<CaptureData> {
  const r = await fetch(`${API}/jobs/${jobId}/capture`);
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function saveCaptureDraft(
  jobId: string,
  blocks: { id: number; subtitle: string }[],
): Promise<{ ok: boolean; message?: string; capture: CaptureData }> {
  const r = await fetch(`${API}/jobs/${jobId}/capture`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks, saved_by: "user" }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function finalizeCapture(
  jobId: string,
  blocks: { id: number; subtitle: string }[],
): Promise<{
  ok: boolean;
  message?: string;
  voiceover_started?: boolean;
  capture: CaptureData;
  stages?: PipelineStage[];
}> {
  const r = await fetch(`${API}/jobs/${jobId}/capture/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks, saved_by: "user" }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function splitCaptureBlock(
  jobId: string,
  blockId: number,
  atSeconds: number,
): Promise<{ ok: boolean; message?: string; capture: CaptureData }> {
  const r = await fetch(`${API}/jobs/${jobId}/capture/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ block_id: blockId, at_seconds: atSeconds }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function mergeCaptureBlock(
  jobId: string,
  blockId: number,
): Promise<{ ok: boolean; message?: string; capture: CaptureData }> {
  const r = await fetch(`${API}/jobs/${jobId}/capture/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ block_id: blockId }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function rebuildCaptureBlocks(
  jobId: string,
): Promise<{ ok: boolean; message?: string; capture: CaptureData }> {
  const r = await fetch(`${API}/jobs/${jobId}/capture/rebuild`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function saveCaptureLayout(
  jobId: string,
  layout: Partial<SubtitleLayout>,
): Promise<{ ok: boolean; message?: string; capture: CaptureData; stages?: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/capture/layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(layout),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function fetchSubtitleEdit(jobId: string): Promise<SubtitleEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/subtitles/edit`);
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function saveSubtitleEdit(
  jobId: string,
  payload: {
    layout?: SubtitleLayout;
    cues?: SubtitleCue[];
  },
): Promise<{ ok: boolean; message?: string; subtitles: SubtitleEditData }> {
  const body: Record<string, unknown> = { saved_by: "user" };
  if (payload.layout) {
    Object.assign(body, payload.layout);
  }
  if (payload.cues) {
    body.cues = payload.cues.map((c) => ({
      cue_id: c.cue_id,
      text: c.text,
      source_segment_id: c.source_segment_id,
      start: c.start,
      end: c.end,
    }));
  }
  const r = await fetch(`${API}/jobs/${jobId}/subtitles/edit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export type VoiceoverScriptBlock = {
  cue_id: string;
  start: number;
  end: number;
  subtitle_text: string;
  voiceover_text: string;
};

export type VoiceoverScriptEditData = {
  job_id: string;
  video_url: string;
  video_filename: string;
  approved_subtitles: boolean;
  approved_voiceover: boolean;
  fully_approved: boolean;
  blocks: VoiceoverScriptBlock[];
  updated_at?: string | null;
};

export async function fetchVoiceoverScriptEdit(jobId: string): Promise<VoiceoverScriptEditData> {
  const r = await fetch(`${API}/jobs/${jobId}/voiceover-script/edit`);
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function saveVoiceoverScriptEdit(
  jobId: string,
  blocks: VoiceoverScriptBlock[],
): Promise<{
  ok: boolean;
  message?: string;
  voiceover_script: VoiceoverScriptEditData;
  stages?: PipelineStage[];
}> {
  const r = await fetch(`${API}/jobs/${jobId}/voiceover-script/edit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ blocks }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function approveVoiceoverScriptPart(
  jobId: string,
  part: "subtitles" | "voiceover",
): Promise<{
  ok: boolean;
  message?: string;
  voiceover_script: VoiceoverScriptEditData;
  stages?: PipelineStage[];
}> {
  const r = await fetch(`${API}/jobs/${jobId}/voiceover-script/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ part }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function runSubtitleFinalVoiceover(
  jobId: string,
): Promise<{ ok: boolean; message?: string; stages?: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/subtitles/final-voiceover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

/** @deprecated use saveSubtitleEdit */
export async function saveSubtitleLayout(
  jobId: string,
  layout: SubtitleLayout,
): Promise<{ ok: boolean; message?: string; subtitles: SubtitleEditData }> {
  return saveSubtitleEdit(jobId, { layout });
}

export async function rerunStage(
  jobId: string,
  stageId: string,
): Promise<{ ok: boolean; message?: string; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/stages/${stageId}/rerun`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function executeStage(
  jobId: string,
  stageId: string,
): Promise<{ ok: boolean; message?: string; stages: PipelineStage[] }> {
  const r = await fetch(`${API}/jobs/${jobId}/stages/${stageId}/execute`, { method: "POST" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(parseErrorDetail(err));
  }
  return r.json();
}

export async function fetchReview(jobId: string) {
  const r = await fetch(`${API}/jobs/${jobId}/review`);
  if (!r.ok) throw new Error("Ошибка загрузки согласований");
  return r.json();
}

export async function approveItem(jobId: string, reviewId: string) {
  const r = await fetch(`${API}/jobs/${jobId}/review/${reviewId}/approve`, { method: "POST" });
  if (!r.ok) throw new Error("Ошибка сохранения");
  return r.json();
}

export async function keepItem(jobId: string, reviewId: string) {
  const r = await fetch(`${API}/jobs/${jobId}/review/${reviewId}/keep`, { method: "POST" });
  if (!r.ok) throw new Error("Ошибка сохранения");
  return r.json();
}

/** URL для превью видео/аудио */
export function mediaUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

/** URL для скачивания артефакта (MP4 и др.) */
export function artifactDownloadUrl(jobId: string, filename: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(filename)}?download=1`;
}
