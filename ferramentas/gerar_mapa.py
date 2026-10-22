"""Converte a malha de UFs do IBGE em caminhos SVG simplificados (projeção equirretangular ajustada)."""
import json, math, sys
src, out = sys.argv[1], sys.argv[2]
COD = {"11":"ro","12":"ac","13":"am","14":"rr","15":"pa","16":"ap","17":"to","21":"ma","22":"pi","23":"ce","24":"rn",
       "25":"pb","26":"pe","27":"al","28":"se","29":"ba","31":"mg","32":"es","33":"rj","35":"sp","41":"pr","42":"sc",
       "43":"rs","50":"ms","51":"mt","52":"go","53":"df"}
d = json.load(open(src, encoding="utf-8"))
polys = {}
for f in d["features"]:
    g = f["geometry"]; uf = COD[f["properties"]["codarea"]]
    rings = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    polys[uf] = [p[0] for p in rings]  # só o contorno externo de cada polígono
allpts = [pt for rs in polys.values() for r in rs for pt in r]
lon0, lon1 = min(p[0] for p in allpts), max(p[0] for p in allpts)
lat0, lat1 = min(p[1] for p in allpts), max(p[1] for p in allpts)
k = math.cos(math.radians((lat0 + lat1) / 2))
W = 600
sc = W / ((lon1 - lon0) * k)
H = round((lat1 - lat0) * sc)
proj = lambda p: ((p[0] - lon0) * k * sc, (lat1 - p[1]) * sc)

def rdp(pts, eps):
    if len(pts) < 3: return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1; n = math.hypot(dx, dy) or 1e-9
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        dd = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n
        if dd > dmax: dmax, idx = dd, i
    if dmax > eps:
        return rdp(pts[:idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]

res = {"w": W, "h": H, "uf": {}}
for uf, rings in polys.items():
    parts, best = [], None
    for r in rings:
        pts = [proj(p) for p in r]
        if pts[0] == pts[-1]: pts = pts[:-1]
        far = max(range(len(pts)), key=lambda i: (pts[i][0]-pts[0][0])**2 + (pts[i][1]-pts[0][1])**2)
        s = rdp(pts[:far + 1], 0.6)[:-1] + rdp(pts[far:] + [pts[0]], 0.6)[:-1]
        if len(s) < 4: continue
        parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in s) + "Z")
        # centróide do maior anel (para o rótulo)
        A = cx = cy = 0
        for (x1, y1), (x2, y2) in zip(s, s[1:] + s[:1]):
            c = x1 * y2 - x2 * y1; A += c; cx += (x1 + x2) * c; cy += (y1 + y2) * c
        if A and (best is None or abs(A) > abs(best[0])): best = (A, cx / (3 * A), cy / (3 * A))
    res["uf"][uf] = {"d": "".join(parts), "c": [round(best[1], 1), round(best[2], 1)], "a": round(abs(best[0]) / 2)}
txt = json.dumps(res, separators=(",", ":"))
open(out, "w", encoding="utf-8").write(txt)
print("ufs", len(res["uf"]), "| viewBox", W, H, "| tamanho", len(txt), "bytes")
