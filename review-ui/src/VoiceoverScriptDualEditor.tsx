import { useEffect, useState } from "react";
import {
  approveVoiceoverScriptPart,
  mediaUrl,
  saveVoiceoverScriptEdit,
  type VoiceoverScriptBlock,
  type VoiceoverScriptEditData,
} from "./api";

type Props = {
  jobId: string;
  data: VoiceoverScriptEditData;
  embedded?: boolean;
  onUpdate: (stages?: import("./api").PipelineStage[]) => void;
  onInfo: (msg: string) => void;
  onError: (msg: string) => void;
};

function formatTime(sec: number): string {
  const m = Math.floor(Math.max(0, sec) / 60);
  const s = Math.floor(Math.max(0, sec) % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function VoiceoverScriptDualEditor({
  jobId,
  data,
  embedded,
  onUpdate,
  onInfo,
  onError,
}: Props) {
  const [blocks, setBlocks] = useState<VoiceoverScriptBlock[]>(data.blocks);
  const [approvedSubtitles, setApprovedSubtitles] = useState(Boolean(data.approved_subtitles));
  const [approvedVoiceover, setApprovedVoiceover] = useState(Boolean(data.approved_voiceover));
  const [saving, setSaving] = useState(false);
  const [busyPart, setBusyPart] = useState<"subtitles" | "voiceover" | null>(null);

  useEffect(() => {
    setBlocks(data.blocks);
    setApprovedSubtitles(Boolean(data.approved_subtitles));
    setApprovedVoiceover(Boolean(data.approved_voiceover));
  }, [data.updated_at, data.blocks, data.approved_subtitles, data.approved_voiceover]);

  const applyScriptPayload = (script: VoiceoverScriptEditData) => {
    setBlocks(script.blocks);
    setApprovedSubtitles(Boolean(script.approved_subtitles));
    setApprovedVoiceover(Boolean(script.approved_voiceover));
  };

  const updateBlock = (cueId: string, field: "subtitle_text" | "voiceover_text", value: string) => {
    setBlocks((prev) =>
      prev.map((b) => (b.cue_id === cueId ? { ...b, [field]: value } : b)),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    onError("");
    try {
      const res = await saveVoiceoverScriptEdit(jobId, blocks);
      onInfo(res.message ?? "Сохранено.");
      if (res.voiceover_script) applyScriptPayload(res.voiceover_script);
      onUpdate(res.stages);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  const handleApprove = async (part: "subtitles" | "voiceover") => {
    setBusyPart(part);
    onError("");
    try {
      // Сначала сохраняем тексты; утверждение другой колонки не сбрасывается, если текст не меняли
      const saved = await saveVoiceoverScriptEdit(jobId, blocks);
      if (saved.voiceover_script) applyScriptPayload(saved.voiceover_script);
      const res = await approveVoiceoverScriptPart(jobId, part);
      onInfo(res.message ?? "Утверждено.");
      if (res.voiceover_script) applyScriptPayload(res.voiceover_script);
      onUpdate(res.stages);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Ошибка утверждения");
    } finally {
      setBusyPart(null);
    }
  };

  return (
    <div className={`cleanup-editor ${embedded ? "cleanup-editor-embedded" : ""}`}>
      {!embedded && <h3>Текст озвучки и субтитры</h3>}
      <p className="hint">
        Слева — текст субтитров (на экране). Справа — текст только для озвучки (может отличаться).
        Сохраните, затем утвердите каждую колонку отдельно.
      </p>

      <video
        className="dual-script-video"
        src={mediaUrl(data.video_url)}
        controls
        playsInline
        style={{ width: "100%", maxHeight: 320, background: "#0f172a", borderRadius: 8 }}
      />

      <div className="dual-script-status" style={{ margin: "10px 0", display: "flex", gap: 16 }}>
        <span style={{ color: approvedSubtitles ? "#166534" : "#92400e" }}>
          Субтитры: {approvedSubtitles ? "утверждены ✓" : "ждут утверждения"}
        </span>
        <span style={{ color: approvedVoiceover ? "#166534" : "#92400e" }}>
          Озвучка: {approvedVoiceover ? "утверждена ✓" : "ждёт утверждения"}
        </span>
      </div>

      <div className="dual-script-list">
        {blocks.map((b) => (
          <div key={b.cue_id} className="dual-script-block">
            <div className="dual-script-time">
              {formatTime(b.start)}–{formatTime(b.end)}
            </div>
            <div className="dual-script-pair">
              <label>
                <span>Субтитры</span>
                <textarea
                  value={b.subtitle_text}
                  onChange={(e) => updateBlock(b.cue_id, "subtitle_text", e.target.value)}
                  rows={2}
                />
              </label>
              <label>
                <span>Для озвучки</span>
                <textarea
                  value={b.voiceover_text}
                  onChange={(e) => updateBlock(b.cue_id, "voiceover_text", e.target.value)}
                  rows={2}
                />
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="cleanup-actions" style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button type="button" className="btn-secondary" disabled={saving || Boolean(busyPart)} onClick={() => void handleSave()}>
          {saving ? "Сохранение…" : "Сохранить оба текста"}
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={saving || Boolean(busyPart) || approvedSubtitles}
          onClick={() => void handleApprove("subtitles")}
        >
          {busyPart === "subtitles" ? "…" : approvedSubtitles ? "Субтитры ✓" : "Утвердить субтитры"}
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={saving || Boolean(busyPart) || approvedVoiceover}
          onClick={() => void handleApprove("voiceover")}
        >
          {busyPart === "voiceover" ? "…" : approvedVoiceover ? "Озвучка ✓" : "Утвердить текст озвучки"}
        </button>
      </div>
    </div>
  );
}
