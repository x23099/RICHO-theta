"""Offline aggregation of local vehicle-feature matches, NOT calibration.

A small local offset is necessary evidence about repeatable appearance, never
proof of a correct camera model, physical pose, cone contact, or FFB readiness.
This tool reads diagnostic CSVs only. It cannot open cameras, register/warp
images, choose/modify calibration, publish ROS, or drive hardware.
"""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class ViewConsistencySettings:
    min_reliable_regions: int = 2
    max_local_offset_px: float = 2.0
    min_ncc: float = 0.8
    min_peak_margin: float = 0.02
    max_reverse_error_px: float = 1.0

    def __post_init__(self):
        if type(self.min_reliable_regions) is not int or self.min_reliable_regions < 2:
            raise ValueError("at least two distinct reliable regions required")
        values = asdict(self)
        if any(type(v) is bool or not math.isfinite(v) for v in values.values()):
            raise ValueError("finite numeric thresholds required")
        if not (0 <= self.min_ncc <= 1 and 0 < self.min_peak_margin <= 2
                and self.max_reverse_error_px >= 0 and self.max_local_offset_px >= 0):
            raise ValueError("thresholds outside supported bounds")


def assess_local_view(rows, settings=None):
    """Classify ONE reference/current pair using all supplied distinct regions.

    NCC, peak separation, reverse error and search boundary are rechecked: the
    exported reliable flag alone is not trusted. One shifted reliable region
    blocks appearance agreement; zero/unreliable matches mean UNKNOWN, not 0px.
    Invalid or duplicate evidence also fails closed. No ground truth is used.
    """
    settings = settings or ViewConsistencySettings()
    names, reliable, shifted, invalid, unreliable = set(), [], [], [], []
    for index, row in enumerate(rows):
        name = str(row.get("region", "")).strip()
        if not name or name in names:
            invalid.append(name or f"row_{index}")
            continue
        names.add(name)
        try:
            x, y, ncc, margin, reverse, search = (
                float(row[k]) for k in ("delta_x_current_minus_reference_px", "delta_y_current_minus_reference_px",
                                       "ncc", "separated_peak_margin", "reverse_return_error_px", "search_margin_px"))
            if (not all(math.isfinite(v) for v in (x, y, ncc, margin, reverse, search))
                    or not -1 <= ncc <= 1.000001 or not 0 <= margin <= 2.000001
                    or reverse < 0 or search < 4 or abs(x) > search or abs(y) > search
                    or not all(v.is_integer() for v in (x, y, reverse, search))):
                raise ValueError("invalid local matching diagnostics")
        except (KeyError, TypeError, ValueError):
            invalid.append(name)
            continue
        good = (ncc >= settings.min_ncc and margin >= settings.min_peak_margin
                and reverse <= settings.max_reverse_error_px and abs(x) < search and abs(y) < search)
        if not good:
            unreliable.append(name)
            continue
        offset = max(abs(x), abs(y))
        reliable.append((name, offset))
        if offset > settings.max_local_offset_px:
            shifted.append(name)
    if invalid:
        state, reason = "INSUFFICIENT_EVIDENCE", "invalid_or_duplicate_region_diagnostics"
    elif shifted:
        state, reason = "LOCAL_CHANGE_OBSERVED", "reliable_local_offset_exceeds_development_bound"
    elif len(reliable) >= settings.min_reliable_regions:
        state, reason = "LOCAL_APPEARANCE_MATCH", "multiple_local_features_within_development_bound"
    else:
        state, reason = "INSUFFICIENT_EVIDENCE", "too_few_reliable_regions"
    return dict(state=state, reason=reason, appearance_consistent=state == "LOCAL_APPEARANCE_MATCH",
                supplied_regions=len(rows), reliable_regions=len(reliable), shifted_regions=len(shifted),
                unreliable_regions=len(unreliable), invalid_regions=len(invalid),
                shifted_region_names="|".join(shifted), invalid_region_names="|".join(invalid),
                max_reliable_local_offset_px=max((v for _, v in reliable), default=None),
                calibration_validated=False, floor_contact_verified=False, usable_for_ffb=False)


def summarize_pairs(rows, *, reference_column=None, reference_id=None, case_column, settings=None):
    if bool(reference_column) == bool(reference_id):
        raise ValueError("exactly one explicit reference column or reference ID required")
    if not rows:
        raise ValueError("nonempty diagnostic CSV required")
    grouped = defaultdict(list)
    for row in rows:
        reference = row.get(reference_column) if reference_column else reference_id
        case = row.get(case_column)
        if not isinstance(reference, str) or not reference.strip() or not isinstance(case, str) or not case.strip():
            raise ValueError("nonempty reference and case identities required")
        grouped[reference, case].append(row)
    return [dict(reference=reference, case=case, **assess_local_view(group, settings))
            for (reference, case), group in grouped.items()]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=Path, required=True)
    references = parser.add_mutually_exclusive_group(required=True)
    references.add_argument("--reference-column")
    references.add_argument("--reference-id")
    parser.add_argument("--case-column", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        raise ValueError("output must be new; no existing artifact overwrite")
    with args.matches.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    settings = ViewConsistencySettings()
    result = summarize_pairs(rows, reference_column=args.reference_column, reference_id=args.reference_id,
                             case_column=args.case_column, settings=settings)
    args.output_dir.mkdir(parents=True)
    target = args.output_dir/"view_consistency.csv"
    with target.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)
    report = dict(status="COMPLETED_LOCAL_APPEARANCE_CHECK_NOT_CALIBRATION_APPROVAL",
                  settings=asdict(settings), pairs=len(result), region_rows=len(rows),
                  state_counts=dict(Counter(r["state"] for r in result)),
                  reference_column=args.reference_column, reference_id=args.reference_id,
                  case_column=args.case_column, source_sha256={str(p.resolve()): sha256(p)
                      for p in (args.matches, Path(__file__))},
                  output_sha256={target.name: sha256(target)}, physical_output=False,
                  production_settings_changed=False, calibration_selected=False)
    (args.output_dir/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(dict(pairs=len(result), state_counts=report["state_counts"],
                         report=str(args.output_dir/"summary.json")), indent=2))


if __name__ == "__main__":
    main()
