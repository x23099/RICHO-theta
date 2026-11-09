"""A4原寸印刷用の床基準十字A～EをベクターPDFで生成する。"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def main():
    output = Path(__file__).with_name("floor_cross_markers_A4_A-E.pdf")
    width, height = A4
    cx, cy = width / 2, height / 2
    half_span, half_bar = 70 * mm, 10 * mm
    assert abs(width / mm - 210) < 1e-6
    assert abs(height / mm - 297) < 1e-6
    pdf = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
    pdf.setTitle("Floor reference crosses A-E - A4 actual size")
    pdf.setAuthor("THETA floor reference experiment")
    pdf.setSubject("Cross 140 x 140 mm, bar width 20 mm; measure the centre")
    pdf.setViewerPreference("PrintScaling", "None")

    for label in "ABCDE":
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica-Bold", 36)
        pdf.drawCentredString(cx, height - 28 * mm, label)
        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(cx, height - 37 * mm, "FLOOR REFERENCE - CENTRE OF +")

        # A single filled outline avoids seams in the overlapping bars.
        points = [(-half_bar, half_span), (half_bar, half_span),
                  (half_bar, half_bar), (half_span, half_bar),
                  (half_span, -half_bar), (half_bar, -half_bar),
                  (half_bar, -half_span), (-half_bar, -half_span),
                  (-half_bar, -half_bar), (-half_span, -half_bar),
                  (-half_span, half_bar), (-half_bar, half_bar)]
        path = pdf.beginPath()
        path.moveTo(cx + points[0][0], cy + points[0][1])
        for x, y in points[1:]:
            path.lineTo(cx + x, cy + y)
        path.close()
        pdf.drawPath(path, stroke=0, fill=1)

        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(cx, 55 * mm, "Cross: 140 x 140 mm | Bar: 20 mm")
        pdf.drawCentredString(cx, 48 * mm, "A4 | Actual size / 100% | No fit-to-page")
        ruler_y = 30 * mm
        ruler_left, ruler_right = cx - 50 * mm, cx + 50 * mm
        pdf.setLineWidth(0.25 * mm)
        pdf.line(ruler_left, ruler_y, ruler_right, ruler_y)
        for x in (ruler_left, ruler_right):
            pdf.line(x, ruler_y - 2 * mm, x, ruler_y + 2 * mm)
        pdf.setFont("Helvetica", 9)
        pdf.drawCentredString(cx, 22 * mm, "Print check: this line must measure 100 mm")
        pdf.showPage()

    pdf.save()
    print(output)


if __name__ == "__main__":
    main()
