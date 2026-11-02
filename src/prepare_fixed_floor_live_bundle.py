#!/usr/bin/env python3
"""Wrap an ALREADY DERIVED same-session floor model with saved PNG evidence.

No calibration fit, session renaming, camera, inference, ROS or FFB. Physical
placement confirmations are operator declarations, NOT inferred from pixels.
"""
import argparse
import json
from pathlib import Path

from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_fixed_floor_live_load import bounded_regular_bytes, png_digest, validate_live_payload
from cone_fixed_floor_shadow import parse_bundle


def prepare(models, images, config, *, board_on_floor=False, rigid_board=False, static_camera=False):
    if not (board_on_floor is True and rigid_board is True and static_camera is True):
        raise ValueError("explicit floor/rigid-board/static-camera confirmations required")
    settings = load_config(config)[0]
    bundle, _ = parse_bundle(bounded_regular_bytes(models, 512*1024), settings)
    images = [Path(p) for p in images]
    if not images or len(images) > 16 or len({p.parent.resolve() for p in images}) != 1:
        raise ValueError("1..16 PNGs in one receiver output directory required")
    session = bundle["session"]
    evidence = []
    prefix = f"decoded_{session}_f"
    for path in images:
        if not path.name.startswith(prefix) or path.suffix != ".png":
            raise ValueError("PNG belongs to a different model session")
        digits = path.stem[len(prefix):]
        if not digits.isdigit() or int(digits) < 1 or path.name != f"{prefix}{int(digits):06d}.png":
            raise ValueError("exact source frame PNG name required")
        evidence.append(dict(frame=int(digits), file=path.name, sha256=png_digest(path)))
    evidence.sort(key=lambda row: row["frame"])
    bundle["live_evidence"] = dict(schema="same_session_floor_evidence_v1", session=session,
        config_sha256=digest(config), camera_sha256=settings["camera_sha256"], source_frames=evidence,
        board_on_floor_confirmed=True, rigid_board_confirmed=True, static_camera_confirmed=True,
        placement_is_operator_declaration_not_automatic_physical_validation=True)
    payload = (json.dumps(bundle, indent=2, allow_nan=False)+"\n").encode()
    validate_live_payload(payload, settings, digest(config), images[0].parent, session,
                          max(r["frame"] for r in evidence), "baseline")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--evidence-png", type=Path, nargs="+", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--board-on-floor", action="store_true")
    parser.add_argument("--rigid-board", action="store_true")
    parser.add_argument("--static-camera", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = prepare(args.models, args.evidence_png, args.config, board_on_floor=args.board_on_floor,
                      rigid_board=args.rigid_board, static_camera=args.static_camera)
    with args.output.open("xb") as stream:
        stream.write(payload)
    print("Prepared comparison-only model:", args.output)
    print("No geometry fitted or session rebound; press L only in the SAME receiver connection.")


if __name__ == "__main__":
    main()
