"""Recover small targets locally and place highlights near the spoken action."""

from src.services.annotation_target_matching import (
    candidates,
    money_value,
    outside_arrow,
    phrase_focus,
    track_recognized_box,
)
from src.tools.annotation_toolkit.opencv_tools import extract_frame


def recover_annotations(video, suggestions, registry, settings):
    from src.services.grounded_screen_annotations import read_boxes, verify_local_hold
    from src.services.screen_annotation_service import accept_observations

    voices = {
        v["transcript_segment_id"]: v
        for v in registry.load_json("voiceover_segments.json")["segments"]
    }
    results = []
    for ann in suggestions:
        if (
            ann["label"].lower().startswith("момент превышения")
            and str(ann.get("speech_context") or "").lower().startswith("это ")
            and results
            and results[-1].get("placement_confirmed")
            and money_value(results[-1]["label"]) is not None
        ):
            results.append(
                {
                    **ann,
                    "skipped": True,
                    "requires_review": False,
                    "placement_confirmed": False,
                    "skip_reason": "Пояснение уже выделенной суммы, не отдельный объект интерфейса",
                }
            )
            continue
        voice = voices.get(ann.get("linked_segment_id"), {})
        start, end = float(ann["target_start"]), float(ann["target_end"])
        focus = phrase_focus(ann, voice)
        if ann.get("timing_required") and not ann.get("speech_cue"):
            results.append(
                {
                    **ann,
                    "placement_confirmed": False,
                    "requires_review": True,
                    "anchor": None,
                    "timing_error": "Нет однозначного совпадения в готовой речи",
                }
            )
            continue
        times = [round(start + 0.05 + (end - start - 0.1) * i / 4, 3) for i in range(5)]
        base_times = times[:]
        # Probe around the phrase cue as well as across the whole source interval.
        times += [
            round(max(start + 0.05, min(end - 0.05, focus + d)), 3) for d in (0.2, 0.55, 1.0, -0.3)
        ]
        times = sorted(set(times), key=lambda t: abs(t - focus))
        hold_start = start
        if ann.get("speech_cue"):
            hold_start = max(start, focus)
            end = min(end, max(focus + 1.0, float(ann["speech_cue"]["end"]) + 0.35))
            times += [round(focus + d, 3) for d in (0.05, 0.25, 0.5)]
            times = sorted(
                {t for t in times if hold_start <= t <= end}, key=lambda t: abs(t - focus)
            )
        if (
            results
            and results[-1].get("placement_confirmed")
            and results[-1].get("linked_segment_id") == ann.get("linked_segment_id")
        ):
            hold_start = max(hold_start, float(results[-1]["target_end"]))
            times = [t for t in times if t >= hold_start]
        result = {**ann, "placement_confirmed": False, "requires_review": True, "anchor": None}
        diagnostics = []
        for time in times:
            frame = extract_frame(video, time)
            nearby = min(base_times, key=lambda t: abs(t - time))
            boxes = read_boxes(
                frame if time in base_times else extract_frame(video, nearby),
                registry.job_dir / "_ocr_cache",
            )
            found = candidates(
                frame,
                boxes,
                ann,
                registry.job_dir / "_ocr_roi_cache",
                force_zoom=time not in base_times,
            )
            if not found:
                # A loading banner may move the whole report. Read the actual
                # frame before trusting coordinates from a nearby cached frame.
                current_boxes = read_boxes(frame, registry.job_dir / "_ocr_cache")
                found = candidates(frame, current_boxes, ann, registry.job_dir / "_ocr_roi_cache")
            if not found:
                # Cursor occlusion: identify the complete text nearby, then
                # verify the label's pixels at the spoken time and every hold frame.
                for reference_time in sorted(base_times, key=lambda t: abs(t - time)):
                    if abs(reference_time - time) > 3:
                        continue
                    reference_frame = extract_frame(video, reference_time)
                    reference_boxes = read_boxes(reference_frame, registry.job_dir / "_ocr_cache")
                    refs = candidates(
                        reference_frame, reference_boxes, ann, registry.job_dir / "_ocr_roi_cache"
                    )
                    if len(refs) == 1 and track_recognized_box(
                        reference_frame,
                        frame,
                        refs[0],
                        numeric=money_value(ann["label"]) is not None,
                        current_boxes=current_boxes,
                    ):
                        found = [{**refs[0], "reference_time": reference_time}]
                        break
            # Multiple equally matching controls in one frame require context.
            if len(found) != 1:
                diagnostics.append({"time": time, "candidate_count": len(found)})
                continue
            box = found[0]
            observation = {
                "time": time,
                "visible": True,
                "bbox": box["bbox"],
                "confidence": 0.99,
                "evidence": (
                    "Сопровождение ранее распознанного текста: "
                    if box.get("reference_time") is not None
                    else "Локальное совпадение: "
                )
                + box["text"],
                "ocr_text": box["text"],
                "cursor": None,
            }
            witnesses = verify_local_hold(video, observation, hold_start, end)
            if witnesses:
                result = accept_observations(
                    ann,
                    witnesses,
                    [w["time"] for w in witnesses],
                    settings.screen_annotation_auto_confidence,
                )
                result.update(
                    anchor_source="local_ocr_verified",
                    speech_focus=round(focus, 3),
                    matched_text=box["text"],
                    reference_time=box.get("reference_time"),
                )
                result = outside_arrow(result)
                break
        result["recovery_diagnostics"] = diagnostics
        results.append(result)
        registry.save_json("annotation_recovery_progress.json", {"items": results})
    return results
