"""Gera a base do 1º turno por município (Presidente), usada pela previsão do 2º turno.

Uso: python ferramentas/base_1t.py 6257 previsao/base1t-6257.json
Para cada município: [uf, eleitorado, comparecimento, válidos, brancos, nulos, votos por candidato...]
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from apuracao_servidor import BASE, get_resultado, get_json, inteiro

ele, saida = sys.argv[1], sys.argv[2]
cfg = get_json(f"{BASE}ele2026/{ele}/config/mun-e{int(ele):06d}-cm.json")
munis = [(a["cd"].lower(), m["cd"], m.get("nm", "")) for a in cfg["abr"] for m in a["mu"]]
print("municípios na configuração:", len(munis), flush=True)

def baixa(item):
    uf, cd, nm = item
    url = f"{BASE}ele2026/{ele}/dados/{uf}/{uf}{cd}-c0001-e{int(ele):06d}-u.json"
    for tentativa in range(4):
        try:
            d = get_resultado(url)
            votos = {c["n"]: inteiro(c["vap"]) for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
            e, v, s = d["e"], d["v"], d["s"]
            return cd, {"uf": uf, "nm": nm, "te": inteiro(e["te"]), "c": inteiro(e["c"]), "vv": inteiro(v["vv"]),
                        "vb": inteiro(v.get("vb")), "vn": inteiro(v.get("tvn") or v.get("vn")), "ts": inteiro(s["ts"]),
                        "st": inteiro(s["st"]), "votos": votos}
        except Exception as err:
            ultimo = err; time.sleep(1 + tentativa)
    return cd, {"uf": uf, "nm": nm, "erro": str(ultimo)}

t0 = time.time()
with ThreadPoolExecutor(24) as ex:
    res = dict(ex.map(baixa, munis))
erros = {k: v for k, v in res.items() if "erro" in v}
cands = sorted({n for v in res.values() if "votos" in v for n in v["votos"]}, key=int)
# formato compacto: cabeçalho de candidatos + linhas
base = {"ele": ele, "cands": cands,
        "campos": ["uf", "nome", "eleitorado", "comparecimento", "validos", "brancos", "nulos", "secoes"] + cands,
        "mun": {cd: [v["uf"], v["nm"], v["te"], v["c"], v["vv"], v["vb"], v["vn"], v["ts"]] + [v["votos"].get(n, 0) for n in cands]
                for cd, v in res.items() if "votos" in v}}
os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
json.dump(base, open(saida, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"ok: {len(base['mun'])} municípios, {len(erros)} com erro, {time.time()-t0:.0f}s, {os.path.getsize(saida)//1024} KB", flush=True)
if erros: print("erros:", list(erros.items())[:5])
