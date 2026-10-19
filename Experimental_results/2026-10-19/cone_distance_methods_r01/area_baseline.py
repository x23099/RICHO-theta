"""Fixed-cone bbox area proxy for OFFLINE comparison, not a runtime sensor."""
import math

FIT_CONDITIONS = frozenset(("center_080", "center_200"))


def area_fraction(row, scope):
    """No floor ray, reference distance, frame ID, or future sample is used."""
    from cone_observation import checked_bbox
    x1, y1, x2, y2 = checked_bbox(row, scope.width, scope.height)
    score, label = float(row["confidence"]), float(row["class_id"])
    if not math.isfinite(score) or not math.isfinite(label) or label != 0 or not .5 <= score <= 1:
        raise ValueError("finite cone class0/conf>=.50 required")
    if x1 <= 0 or y1 <= 0 or x2 >= scope.width or y2 >= scope.height:
        raise ValueError("image edge truncation")
    if not all(scope._in_circle(x,y) for x in (x1,x2) for y in (y1,y2)):
        raise ValueError("bbox crosses frozen front circle")
    return (x2-x1)*(y2-y1)/(scope.width*scope.height)


def fit_scale(anchors):
    """Only two prespecified, group-median training anchors may reach the fit."""
    ids = [r["condition"] for r in anchors]
    if len(ids) != 2 or len(set(ids)) != 2 or set(ids) != FIT_CONDITIONS:
        raise ValueError("exactly center080/center200 training anchors required; no holdouts")
    terms = []
    for row in anchors:
        q, z = float(row["q_median"]), float(row["reference_z_m"])
        expected = .8 if row["condition"] == "center_080" else 2.
        if not math.isfinite(q) or not 0 < q < 1 or not math.isclose(z, expected, abs_tol=1e-12, rel_tol=0):
            raise ValueError("valid frozen median area and endpoint reference required")
        terms.append(math.log(z*math.sqrt(q)))
    return math.exp(sum(terms)/len(terms))


def predict_z(q, scale):
    q, scale = float(q), float(scale)
    if not math.isfinite(q) or not 0 < q < 1 or not math.isfinite(scale) or scale <= 0:
        raise ValueError("positive finite area/scale required")
    return scale/math.sqrt(q)
