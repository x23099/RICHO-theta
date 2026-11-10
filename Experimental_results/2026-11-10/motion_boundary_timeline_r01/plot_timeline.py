"""集計CSVから小さいSVGグラフを生成。カメラ画像には触れない。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def run(csv_path, output):
    if output.exists():raise ValueError("new SVG path required")
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:raise ValueError("nonempty local window required")
    times = [float(r["relative_source_sec"]) for r in rows]
    lo, hi = min(times), max(times)
    if hi <= lo:raise ValueError("nonzero source time window required")
    left, right = 95, 965
    def x(t):return left+(t-lo)/(hi-lo)*(right-left)
    def y(v):return 240-(v-.60)/.14*160
    colours = {"numeric_clear_of_body_boundary": "#0072b2", "numeric_body_boundary_conflict": "#d55e00",
               "boundary_withheld_body_boundary_conflict": "#555555"}
    lanes = {"numeric_clear_of_body_boundary": 310, "numeric_body_boundary_conflict": 350,
             "boundary_withheld_body_boundary_conflict": 390}
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="500" viewBox="0 0 1000 500">',
           '<rect width="1000" height="500" fill="white"/>',
           '<g font-family="sans-serif" font-size="12" fill="#222">',
           '<text x="95" y="22" font-size="17">Recorded range / native body-boundary review</text>',
           '<text x="95" y="43">Offline coordinate audit; NOT physical ground truth or GUI hold duration</text>']
    for value in (.60, .62, .64, .66, .68, .70, .72, .74):
        yy = y(value)
        svg.append(f'<line x1="{left}" y1="{yy:.2f}" x2="{right}" y2="{yy:.2f}" stroke="#ddd"/>')
        svg.append(f'<text x="55" y="{yy+4:.2f}">{value:.2f}</text>')
    svg.append('<text x="15" y="65">range [m]</text>')
    for state, yy in lanes.items():
        svg.append(f'<line x1="{left}" y1="{yy}" x2="{right}" y2="{yy}" stroke="#ddd"/>')
        label = {"numeric_clear_of_body_boundary": "clear*", "numeric_body_boundary_conflict": "numeric*",
                 "boundary_withheld_body_boundary_conflict": "withheld*"}[state]
        svg.append(f'<text x="15" y="{yy+4}">{label}</text>')
    for t, r in zip(times, rows):
        colour = colours.get(r["state"], "#999")
        xx = x(t)
        if r["range_m"]:
            value = float(r["range_m"])
            if not .60 <= value <= .74:
                raise ValueError("numeric value outside declared plot range; adjust axis explicitly")
            svg.append(f'<circle cx="{xx:.2f}" cy="{y(value):.2f}" r="2.1" fill="{colour}"/>')
        if r["state"] in lanes:
            svg.append(f'<circle cx="{xx:.2f}" cy="{lanes[r["state"]]}" r="2" fill="{colour}"/>')
    for tick in range(int(lo)+1, int(hi)+1):
        xx = x(tick)
        svg.append(f'<line x1="{xx:.2f}" y1="407" x2="{xx:.2f}" y2="413" stroke="#444"/>')
        svg.append(f'<text x="{xx-10:.2f}" y="430">{tick}</text>')
    svg.extend(['<text x="280" y="450">source receive-time [s], relative to the first record</text>',
        '<text x="95" y="473">* blue: clear of reviewed local body edge; orange: numeric at/near edge; grey: withheld at/near edge</text>',
        '<text x="95" y="491">Individual recorded points only. No interpolation, extrapolation, camera overlay or metric correction.</text>',
        '</g></svg>'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:stream.write("\n".join(svg)+"\n")
    metadata = dict(input_csv=str(csv_path), input_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        plotted_records=len(rows), source_time_range=[lo, hi],
        output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        camera_images_modified=False, physical_accuracy_measured=False)
    with output.with_suffix(".json").open("x") as stream:
        json.dump(metadata, stream, indent=2);stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args();run(args.csv, args.output)
