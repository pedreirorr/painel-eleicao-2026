"""Coleta ao vivo da apuração por município (2º turno) e roda o modelo de previsão.

A cada ciclo: lê os 28 arquivos de acompanhamento (UF-e{ele}-ab.json), que dizem quantas seções de cada
município já foram totalizadas; baixa só os municípios que mudaram; roda previsao/modelo.py.
"""
import json, os, time, datetime
from concurrent.futures import ThreadPoolExecutor
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from apuracao_servidor import BASE, get_json, get_resultado, inteiro, UFS, log
import modelo

PESQUISAS_A = 0.5104   # média das pesquisas pós-1º turno (última de cada instituto): parcela de A nos válidos


class Coletor:
    def __init__(self, ciclo, cd2, cd1):
        self.ciclo, self.cd2 = ciclo, cd2
        raw = json.load(open(os.path.join(os.path.dirname(__file__), f"base1t-{cd1}.json"), encoding="utf-8"))
        # A = mais votado no 1º turno entre os dois finalistas (descobertos no arquivo do 2º turno)
        br = get_resultado(self.url("br"))
        finalistas = [c["n"] for a in br["carg"][0]["agr"] for p in a["par"] for c in p["cand"]]
        ix = {k: i for i, k in enumerate(raw["campos"])}
        tot = {n: sum(r[ix[n]] for r in raw["mun"].values()) for n in finalistas if n in ix}
        self.A, self.B = sorted(tot, key=lambda n: -tot[n])[:2]
        modelo.configurar(self.A, self.B)
        self.base = modelo.preparar_base(raw)
        self.t0 = self._calibra_t0(PESQUISAS_A)
        self.status, self.atual = {}, {}
        log(f"Previsão: A={self.A}, B={self.B}, {len(self.base)} municípios, t0={self.t0:.3f}")

    def url(self, uf, mun=""):
        return f"{BASE}{self.ciclo}/{self.cd2}/dados/{uf}/{uf}{mun}-c0001-e{int(self.cd2):06d}-u.json"

    def _calibra_t0(self, alvo):
        lo, hi = 0.0, 1.0
        for _ in range(30):
            mid = (lo + hi) / 2
            p = modelo.projetar(self.base, {}, mid, sims=1)["pA"]
            lo, hi = (mid, hi) if p < alvo else (lo, mid)
        return (lo + hi) / 2

    def _ab(self, uf):
        return get_json(f"{BASE}{self.ciclo}/{self.cd2}/dados/{uf}/{uf}-e{int(self.cd2):06d}-ab.json?nocache={int(time.time()*1000)}")

    def _muni(self, item):
        uf, cd = item
        d = get_resultado(self.url(uf, cd))
        votos = {c["n"]: inteiro(c["vap"]) for a in d["carg"][0]["agr"] for p in a["par"] for c in p["cand"]}
        s, e, v = d["s"], d["e"], d["v"]
        ts = max(1, inteiro(s["ts"]))
        return cd, {"a": votos.get(self.A, 0), "b": votos.get(self.B, 0), "est": inteiro(e.get("est")),
                    "c": inteiro(e.get("c")), "vv": inteiro(v.get("vv")), "f": inteiro(s["st"]) / ts}

    def ciclo_(self):
        with ThreadPoolExecutor(8) as ex:
            abs_ = list(ex.map(lambda u: (u, self._ab(u)), UFS))
        mudou = []
        for uf, d in abs_:
            for m in d.get("abr", []):
                if m.get("tpabr") != "mun": continue
                cd, st = m["cdabr"], inteiro(m["s"]["st"])
                chave = (st, m.get("ht"))
                if st > 0 and self.status.get(cd) != chave:
                    mudou.append((uf, cd)); self.status[cd] = chave
        if mudou:
            with ThreadPoolExecutor(32) as ex:
                for r in ex.map(lambda it: self._seguro(it), mudou):
                    if r: self.atual[r[0]] = r[1]
        p = modelo.projetar(self.base, self.atual, self.t0, sims=1500)
        p.update({"A": self.A, "B": self.B, "t0": self.t0, "municipios_apurados": len(self.atual),
                  "atualizados_no_ciclo": len(mudou), "calculado": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                  "pesquisas_A": PESQUISAS_A})
        p["uf"] = {k: round(v, 5) for k, v in p["uf"].items()}
        return p

    def _seguro(self, it):
        for t in range(3):
            try: return self._muni(it)
            except Exception: time.sleep(1 + t)
        self.status.pop(it[1], None)   # tenta de novo no próximo ciclo
        return None
