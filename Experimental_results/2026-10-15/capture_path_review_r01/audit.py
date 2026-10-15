"""Read-only recording metadata/current source review; no hardware access."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    target = HERE/"audit.json"
    if target.exists():
        raise ValueError("no audit overwrite")
    day = HERE.parent
    inputs = []
    for directory in ("cone_static_distance_r01", "cone_floor_reference_real_r01", "floor_cone_same_pose_analysis_r01"):
        intake_path = day/directory/"intake_summary.json"
        intake = json.loads(intake_path.read_text())
        for entry in intake.get("inputs", [intake]):
            path = Path(entry.get("path", entry.get("session")))/"metadata.json"
            data = json.loads(path.read_text())
            inputs.append(dict(session=path.parent.name, metadata=str(path), sha256=sha256(path),
                               camera_capture_properties=data["camera_capture_properties"],
                               historical_code_commit_recorded=any(k in data for k in ("git_commit", "commit", "git"))))
    captures = [r["camera_capture_properties"] for r in inputs]
    assert len(inputs) == 8 and all(r == captures[0] for r in captures)
    assert captures[0]["frame_width"] == 1280 and captures[0]["frame_height"] == 720
    assert captures[0]["fps"] == 30 and captures[0]["fourcc_text"] == "MJPG"
    source_path = ROOT/"src/bird_eye.py"
    code = source_path.read_text()
    tree = ast.parse(code)
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
               and node.name in ("update_frame", "record_frames", "_open_recording_writers")}
    update = methods["update_frame"]
    calls = [n for n in ast.walk(update) if isinstance(n, ast.Call)]
    recording = [n for n in calls if ast.unparse(n.func) == "self.record_frames"]
    assert len(recording) == 1 and ast.unparse(recording[0].args[0]) == "frame"
    read = [n for n in calls if ast.unparse(n.func) == "self.cap.read"]
    assert len(read) == 1
    raw_write = [n for n in ast.walk(methods["record_frames"]) if isinstance(n, ast.Call)
                 and ast.unparse(n.func) == "self.recording_writers['raw'].write"]
    assert len(raw_write) == 1 and ast.unparse(raw_write[0].args[0]) == "raw_frame"
    transforms = [dict(line=n.lineno, call=ast.unparse(n)) for n in calls
                  if ast.unparse(n.func) in ("cv2.resize", "cv2.flip", "cv2.rotate", "cv2.warpAffine", "cv2.warpPerspective")]
    # These are only direct calls in the current update method. Do not infer that
    # camera firmware/backend, called helpers, or historical code are attested.
    assert not transforms
    photos = []
    from PIL import Image
    for name in ("IMG_0799.jpeg", "IMG_0800.jpeg"):
        p = Path("/home/robo25/Downloads")/name
        with Image.open(p) as image:
            photos.append(dict(path=str(p), sha256=sha256(p), stored_size=list(image.size),
                               exif_orientation=image.getexif().get(274), file_changed=False))
    report = dict(status="COMPLETED_CAPTURE_METADATA_AND_CURRENT_CODE_REVIEW_NOT_ROOT_CAUSE_OR_CALIBRATION_APPROVAL",
                  user_confirmation=dict(
                      verbatim="聞かれたことに関しては全て問題ないです。",
                      scope="previous questions: mounting play, cable pull, lens-ground distance origin, removal/reinstallation or equipment/load changes",
                      interpretation="user reports no issues; not independently measured by assistant",
                      intentional_height_or_tilt_change_reported=False,
                      mounting_fault_established=False),
                  photos=photos, metadata_sessions=inputs, capture_properties_equal_all_eight=True,
                  current_source=dict(path=str(source_path), sha256=sha256(source_path),
                      capture_read_line=read[0].lineno, record_call_line=recording[0].lineno,
                      raw_write_line=raw_write[0].lineno, direct_geometric_transform_calls_in_update=transforms),
                  limits=["source audit covers current code, not a proven historical executable snapshot",
                          "reported OpenCV properties do not attest hidden camera/capture-device processing",
                          "-1 controls can mean unsupported, not proof that exposure/white balance was fixed",
                          "local feature changes do not uniquely identify camera pose or a mechanical fault",
                          "photos are not metric calibration measurements"],
                  changed_runtime_code=False, changed_parameters=False, physical_output=False,
                  source_sha256={str(Path(__file__)): sha256(Path(__file__))})
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n")
    print(json.dumps(dict(metadata_sessions=len(inputs), capture_properties_equal=True,
                         current_raw_recording_lines=[read[0].lineno, recording[0].lineno, raw_write[0].lineno],
                         mechanical_fault_assumed=False), indent=2))


if __name__ == "__main__":
    main()
