"""Deterministic SVG analysis figures, with original PNG bytes embedded intact."""
import base64
from html import escape
import json
from pathlib import Path
import sys

import cairosvg

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256

NS='http://www.w3.org/2000/svg'
HEADER=148;WIDTH=1280;HEIGHT=980


def text(x,y,value,size=20,color='#e9eff6',weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'


def svg_for(row,png_bytes):
    available=row['diagnostic_available']=='True'
    if available and not row['diagnostic_z_m']:raise ValueError('available distance must come from the exact saved row')
    if not available and row['diagnostic_z_m']:raise ValueError('withheld distance must stay absent, never display raw rejected candidate')
    value=f"{float(row['diagnostic_z_m']):.3f} m" if available else '保留（数値なし）'
    reference=f"{float(row['reference_z_m']):.2f} m"
    colour='#6adbed' if available else '#ffcd83'
    metadata=json.dumps(dict(source_session=row['session'],source_frame=int(row['frame']),source_time_sec=row['time_sec'],
        raw_diagnostic_z_m=row['diagnostic_z_m'],reference_z_m=row['reference_z_m'],original_png_sha256=row['original_png_sha256'],
        post_recording_visualization=True,physical_metric_verified=False,usable_for_ffb=False),ensure_ascii=False)
    parts=[f'<svg xmlns="{NS}" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<title>コーン測距：録画後の再計算を表示した解析画像</title>',
        f'<metadata>{escape(metadata)}</metadata>',
        '<rect width="1280" height="980" fill="#111c2b"/>',
        '<g font-family="Noto Sans CJK JP, sans-serif">',
        text(24,35,'コーン測距の解析画像｜録画後の再計算',27,weight=700),
        text(1010,33,'条件付き診断値',20,'#ffcd83',700),
        text(24,94,'推定 Z = '+value,43,colour,700),
        text(762,91,'設置 Z（申告）= '+reference,27,'#dbe4ed',500),
        text(26,129,f"撮影：2026-10-15 ／ frame {int(row['frame'])} ／ 録画時刻 {float(row['time_sec']):.3f} s",20),
        f'<image id="original-native-frame" x="0" y="{HEADER}" width="1280" height="720" preserveAspectRatio="none" xlink:href="data:image/png;base64,{base64.b64encode(png_bytes).decode()}"/>']
    if available:
        pair=json.loads(row['native_colour_pair_json']);x,y=map(float,pair[1]);y+=HEADER
        if not 0<=x<640 or not HEADER<=y<HEADER+720:raise ValueError('native front-lens measurement point required')
        box_x=390;box_y=y-82
        parts.extend([f'<path d="M {x} {y} L {box_x} {box_y+62}" stroke="#ffe082" stroke-width="2" fill="none"/>',
            f'<circle id="observed-bottom-marker" cx="{x}" cy="{y}" r="6" fill="#ffe082" stroke="#111c2b" stroke-width="2"/>',
            f'<rect x="{box_x}" y="{box_y}" width="360" height="76" rx="8" fill="#111c2b" fill-opacity="0.92" stroke="#ffe082"/>',
            text(box_x+14,box_y+27,'測距に使用した画像上の下端',22,'#ffe082',500),
            text(box_x+14,box_y+60,'推定 Z = '+value,27,'#ffffff',700)])
    else:
        parts.extend(['<rect x="30" y="760" width="860" height="76" rx="8" fill="#111c2b" fill-opacity="0.95" stroke="#ffcd83"/>',
            text(45,790,'遮蔽区間：距離は出していません',26,'#ffcd83',700),
            text(45,820,'姿勢の根拠不足 ＋ 現在フレームの画像品質が不採用',21,'#ffffff')])
    parts.extend(['<rect x="0" y="868" width="1280" height="112" fill="#111c2b"/>',
        text(24,894,'方式：魚眼校正候補＋過去情報のみの姿勢候補＋床交点（処理完了待ちの模擬条件）',18),
        text(24,920,'基準：カメラ直下 → 台座の車体側の辺 ／ Zは前後方向で、斜め距離ではありません。',18),
        text(24,946,'物理距離・接地点の検証は未完了 ／ 実機FFBへの使用なし',19,'#ffcd83',500),
        text(24,970,'撮影時のリアルタイム表示ではありません。元映像と原画像は別途、無加工で保存しています。',17),
        '</g></svg>'])
    return '\n'.join(parts)+'\n'


def main():
    output=HERE/'visualizations_r01'
    if output.exists():raise ValueError('new visualization output required')
    original=HERE/'originals_r01';proof=json.loads((original/'summary.json').read_text())
    for name,h in proof['output_sha256'].items():assert sha256(original/name)==h,name
    paths=[Path(__file__),original/'summary.json',original/'frame_manifest.csv']
    sources={str(p):sha256(p) for p in paths};rows=read_csv(original/'frame_manifest.csv');outputs=[]
    output.mkdir()
    for r in rows:
        p=original/r['original_png'];assert sha256(p)==r['original_png_sha256'];sources[str(p)]=sha256(p)
        stem=f"{r['label']}_distance_f{int(r['frame']):06d}"
        svg=svg_for(r,p.read_bytes());(output/(stem+'.svg')).write_text(svg)
        cairosvg.svg2png(bytestring=svg.encode(),write_to=str(output/(stem+'.png')))
        outputs.append(dict(label=r['label'],session=r['session'],frame=r['frame'],time_sec=r['time_sec'],
            reference_z_m=r['reference_z_m'],diagnostic_z_m=r['diagnostic_z_m'],diagnostic_available=r['diagnostic_available'],
            svg=stem+'.svg',png=stem+'.png',width=WIDTH,height=HEIGHT,original_png=str(p),original_png_sha256=r['original_png_sha256'],
            photograph_native_width=1280,photograph_native_height=720,photograph_offset_y=HEADER,
            post_recording_visualization=True,physical_metric_verified=False,usable_for_ffb=False))
    write_csv(output/'visualization_manifest.csv',outputs)
    cards=[]
    for r in outputs:
        cards.append(f'<section><h2>{escape(r["label"])}</h2><img src="{r["png"]}" width="1280" height="980" alt="録画後の距離解析画像"/>'
            f'<p><a href="{r["png"]}">PNG</a> ／ <a href="{r["svg"]}">SVG</a> ／ '
            f'<a href="../originals_r01/{Path(r["original_png"]).name}">無加工の原画像</a></p></section>')
    html='<!doctype html><html lang="ja"><meta charset="utf-8"><title>コーン測距の解析画像</title><style>body{max-width:1280px;margin:24px auto;padding:0 16px;font-family:sans-serif;background:#f2f5f7;color:#162331}img{width:100%;height:auto}section{margin:32px 0}a{color:#12647c}</style><h1>コーン測距の解析画像</h1><p>撮影時の画面ではなく録画後の再計算結果です。推定Zと申告設置Zを区別し、未検証の条件付き診断値として表示しています。</p>'+''.join(cards)+'</html>\n'
    (output/'index.html').write_text(html)
    assert all(sha256(Path(p))==h for p,h in sources.items())
    record=dict(status='CREATED_DETERMINISTIC_POST_RECORDING_DISTANCE_FIGURES_NOT_LIVE_SCREENSHOTS',work_date='2026-10-23',source_sha256=sources,
        visualizations=len(outputs),original_images_edited=False,derived_analysis_figures=True,ai_image_generation_used=False,
        svg_embeds_original_png_bytes=True,physical_output=False,usable_for_ffb=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(outputs,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
