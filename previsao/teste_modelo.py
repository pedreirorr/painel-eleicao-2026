"""Teste do modelo de previsão com 2º turnos sintéticos gerados a partir do 1º turno real por município.

Uso: python previsao/teste_modelo.py [n_eleicoes]
"""
import json, math, random, sys, os, statistics
sys.path.insert(0, os.path.dirname(__file__))
import modelo

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
DIFICIL = len(sys.argv) > 2 and sys.argv[2] == "dificil"  # efeitos que o modelo não enxerga
base_raw = json.load(open(os.path.join(os.path.dirname(__file__), "base1t-6257.json"), encoding="utf-8"))
modelo.configurar("22", "13")
base = modelo.preparar_base(base_raw)
ufs = sorted({m["uf"] for m in base.values()})

# t0 que reproduz a média das pesquisas (51,04% para A) sem nenhum dado apurado
def calibra_t0(alvo):
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        p = modelo.projetar(base, {}, mid, sims=1)["pA"]
        lo, hi = (mid, hi) if p < alvo else (lo, mid)
    return (lo + hi) / 2
T0 = calibra_t0(0.5104)
print(f"t0 calibrado nas pesquisas: {T0:.3f}")

CEDO = {"rs", "sc", "pr", "sp", "ms", "mt", "go", "df", "es", "rj", "mg", "ro", "ac"}
NORTE = {"am", "pa", "rr", "ap", "to"}
CHECK = [0.05, 0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95]
res = {c: {"err": [], "naive": [], "cob": 0, "brier": [], "larg": []} for c in CHECK}
acerto_vencedor = {c: 0 for c in CHECK}

for k in range(N):
    rnd = random.Random(1000 + k)
    t_true = rnd.uniform(0.35, 0.65)
    t_uf = {u: t_true + rnd.gauss(0, 0.08) for u in ufs}
    d_uf = {u: rnd.gauss(0, 0.015) for u in ufs}
    comp_uf = {u: rnd.gauss(0.97, 0.02) for u in ufs}
    choque = rnd.gauss(0, 0.02 if DIFICIL else 0.01)  # erro comum que o modelo não vê
    gama = rnd.uniform(-0.6, 0.6) if DIFICIL else 0.0  # transferência ligada ao perfil político do município
    dif_comp = rnd.uniform(-0.06, 0.06) if DIFICIL else 0.0  # comparecimento cai mais num dos lados
    off = {u: (rnd.uniform(0.0, 0.35) if u in CEDO else rnd.uniform(0.35, 0.75) if u not in NORTE else rnd.uniform(0.25, 0.6)) for u in ufs}
    verdade, tempo = {}, {}
    for cd, m in base.items():
        u = m["uf"]
        t_m = min(1, max(0, t_uf[u] + gama * (m["base"] - 0.5)))
        s = m["base"] + m["q"] * (t_m - m["base"]) + d_uf[u] + choque + rnd.gauss(0, 0.025)
        s = min(0.98, max(0.02, s))
        c = m["c1"] * comp_uf[u] * (1 + dif_comp * (m["base"] - 0.5) * 2); vv = c * (m["vv1"] / max(1, m["c1"]))
        verdade[cd] = (s * vv, (1 - s) * vv, c, vv)
        tempo[cd] = off[u] + rnd.uniform(0, 0.25)
    TA = sum(v[0] for v in verdade.values()); TB = sum(v[1] for v in verdade.values())
    final = TA / (TA + TB)
    eleit = sum(m["te"] for m in base.values())
    # municípios grandes são apurados aos poucos (janela de 0,3); os outros, de uma vez
    def estado_em(tt):
        atual = {}
        for cd, m in base.items():
            larg = 0.3 if m["te"] > 300000 else 0.0
            f = 1.0 if tt >= tempo[cd] + larg else (0.0 if tt < tempo[cd] - larg or larg == 0 else (tt - (tempo[cd] - larg)) / (2 * larg))
            if f <= 0: continue
            a, b, c, vv = verdade[cd]
            atual[cd] = {"a": a * f, "b": b * f, "est": m["te"] * f, "c": c * f, "vv": vv * f, "f": f}
        return atual
    for cp in CHECK:
        lo, hi = 0.0, 1.5
        for _ in range(20):
            mid = (lo + hi) / 2
            fr = sum(x["est"] for x in estado_em(mid).values()) / eleit
            lo, hi = (mid, hi) if fr < cp else (lo, mid)
        atual = estado_em(hi)
        p = modelo.projetar(base, atual, T0, sims=400, semente=k)
        oa = sum(x["a"] for x in atual.values()); ob = sum(x["b"] for x in atual.values())
        r = res[cp]
        r["err"].append(p["pA"] - final); r["naive"].append(oa / (oa + ob) - final)
        r["cob"] += p["lo90"] <= final <= p["hi90"]; r["larg"].append(p["hi90"] - p["lo90"])
        r["brier"].append((p["chanceA"] - (final > 0.5)) ** 2)
        acerto_vencedor[cp] += (p["pA"] > 0.5) == (final > 0.5)
    if (k + 1) % 20 == 0: print(f"  {k+1}/{N} eleições simuladas", flush=True)

print(f"\n{'apurado':>8} | {'erro médio do modelo':>21} | {'erro do placar parcial':>22} | {'faixa 90% acerta':>16} | {'largura média':>13} | {'acerta vencedor':>15} | brier")
for cp in CHECK:
    r = res[cp]
    mae = statistics.mean(abs(e) for e in r["err"]) * 100; nae = statistics.mean(abs(e) for e in r["naive"]) * 100
    print(f"{cp*100:7.0f}% | {mae:18.2f} pp | {nae:19.2f} pp | {r['cob']/N*100:15.0f}% | {statistics.mean(r['larg'])*100:10.2f} pp | {acerto_vencedor[cp]/N*100:14.0f}% | {statistics.mean(r['brier']):.3f}")
