"""Previsão do resultado final do 2º turno a partir da apuração parcial, município a município.

Ideia
-----
Para cada município m, a partir do 1º turno:
  base_m = A1 / (A1 + B1)                      parcela de A entre os dois finalistas no 1º turno
  q_m    = K * O1 / (A1 + B1)                  peso dos votos dos eliminados (O1) que voltam como válidos (K)
O 2º turno esperado em m (parcela de A entre os votos válidos) é
  s_m = base_m + q_m * (t - base_m) + delta_uf(m)
onde t = fração dos votos dos eliminados que vai para A (nacional) e delta_uf é um ajuste por estado.
t e delta_uf são estimados por mínimos quadrados ponderados com os municípios já apurados, com
"encolhimento" de delta_uf para zero (pouca informação => pouco ajuste) e uma âncora de t no valor
das pesquisas. Os municípios que faltam (e a parte que falta dos parcialmente apurados) recebem a
previsão do modelo; os votos que ainda vão entrar vêm do eleitorado que falta x comparecimento x
taxa de votos válidos (observados no 2º turno no município, no estado ou no país).
A incerteza vem de simulações: erro de t, de delta_uf e um erro comum nacional que diminui com a apuração.
"""
import math, random

K_ELIMINADOS = 0.75       # parte dos votos dos eliminados que volta como voto válido em A ou B
TAU_UF = 0.015            # desvio típico do ajuste por estado (1,5 p.p.)
SIGMA_SIS0 = 0.015        # erro comum nacional antes da apuração (1,5 p.p.), cai com o % apurado
PRIOR_N0 = 3000           # força da previsão do modelo dentro de um município parcialmente apurado (votos)


def preparar_base(base):
    """base1t (ferramentas/base_1t.py) -> dicionário por município com o que o modelo usa."""
    ix = {k: i for i, k in enumerate(base["campos"])}
    out = {}
    for cd, r in base["mun"].items():
        a1, b1, vv1 = r[ix[A]], r[ix[B]], r[ix["validos"]]
        if a1 + b1 <= 0:
            continue
        o1 = max(0, vv1 - a1 - b1)
        out[cd] = {"uf": r[ix["uf"]], "te": r[ix["eleitorado"]], "c1": r[ix["comparecimento"]], "vv1": vv1,
                   "base": a1 / (a1 + b1), "q": K_ELIMINADOS * o1 / (a1 + b1)}
    return out


A, B = "22", "13"   # candidato A (Flávio) e B (Lula): ajustados por configurar()


def configurar(cand_a, cand_b):
    global A, B
    A, B = cand_a, cand_b


def estimar(base, atual, t0, peso_t0=50.0, iter_=30):
    """Ajusta t e delta_uf com os municípios que têm votos no 2º turno.
    atual[cd] = {"a": votos A, "b": votos B, "est": eleitores apurados, "c": comparecimento, "vv": válidos, "f": fração de seções}
    Peso de cada município: raiz dos votos apurados (municípios grandes pesam mais, sem dominar)."""
    obs = []
    for cd, x in atual.items():
        m = base.get(cd)
        n = x["a"] + x["b"]
        if not m or n < 50:
            continue
        s = x["a"] / n
        obs.append((m["uf"], m["base"], m["q"], s, math.sqrt(n)))
    t, delta = t0, {}
    if not obs:
        return t, delta, {"n": 0, "sigma": 0.03, "se_t": 0.08, "se_uf": {}}
    lam = None
    for _ in range(iter_):
        # t: mínimos quadrados de (s - base - delta) = q (t - base), com âncora nas pesquisas
        num = peso_t0 * t0; den = peso_t0
        for uf, b, q, s, w in obs:
            if q <= 0: continue
            y = s - b - delta.get(uf, 0.0) + q * b
            num += w * q * y; den += w * q * q
        t = num / den
        # delta_uf com encolhimento: lambda equivale a TAU_UF
        res = [(uf, w, s - (b + q * (t - b))) for uf, b, q, s, w in obs]
        sigma2 = sum(w * (r - delta.get(uf, 0.0)) ** 2 for uf, w, r in res) / max(1e-9, sum(w for _, w, _ in res))
        lam = sigma2 / (TAU_UF ** 2) * (sum(w for _, w, _ in res) / len(res))
        acc = {}
        for uf, w, r in res:
            a_ = acc.setdefault(uf, [0.0, 0.0]); a_[0] += w * r; a_[1] += w
        delta = {uf: s_ / (wsum + lam) for uf, (s_, wsum) in acc.items()}
    sigma = math.sqrt(sigma2)
    wq2 = sum(w * q * q for _, _, q, _, w in obs)
    wmean = sum(w for *_, w in obs) / len(obs)
    se_t = math.sqrt(sigma2 * wmean / (wq2 + peso_t0)) if wq2 > 0 else 0.08
    se_uf = {uf: math.sqrt(sigma2 * wmean / (wsum + lam)) for uf, (_, wsum) in acc.items()}
    return t, delta, {"n": len(obs), "sigma": sigma, "se_t": max(se_t, 0.005), "se_uf": se_uf}


def taxas(base, atual):
    """Comparecimento e votos válidos do 2º turno em relação ao 1º: por estado e nacional."""
    acc = {}
    for cd, x in atual.items():
        m = base.get(cd)
        if not m or x["est"] <= 0 or x["c"] <= 0:
            continue
        frac = x["est"] / max(1, m["te"])
        for k in (m["uf"], "BR"):
            d = acc.setdefault(k, [0.0, 0.0, 0.0, 0.0])
            d[0] += x["c"]; d[1] += m["c1"] / max(1, m["te"]) * x["est"]   # comparecimento 2T x esperado pelo 1T
            d[2] += x["vv"]; d[3] += x["c"] * (m["vv1"] / max(1, m["c1"]))  # válidos 2T x esperado pelo 1T
    return {k: (d[0] / d[1] if d[1] else 1.0, d[2] / d[3] if d[3] else 1.0) for k, d in acc.items()}


def projetar(base, atual, t0, sims=2000, semente=1):
    """Projeção do total nacional (e por estado) de A e B. Retorna dicionário pronto para o painel."""
    t, delta, info = estimar(base, atual, t0)
    tx = taxas(base, atual)
    nac = tx.get("BR", (1.0, 1.0))
    # contribuição fixa (votos já apurados) e a parte que falta, por estado
    obsA = obsB = 0.0
    por_uf = {}
    eleit_tot = eleit_apur = 0
    for cd, m in base.items():
        x = atual.get(cd)
        uf = m["uf"]
        ratio_c, ratio_v = tx.get(uf, nac)
        est = x["est"] if x else 0
        rest_e = max(0, m["te"] - est)
        eleit_tot += m["te"]; eleit_apur += est
        if x and x["est"] > 0 and x["c"] > 0:
            comp = x["c"] / x["est"]; val = x["vv"] / x["c"] if x["c"] else 0.95
        else:
            comp = m["c1"] / max(1, m["te"]) * ratio_c
            val = m["vv1"] / max(1, m["c1"]) * ratio_v
        v_rest = rest_e * comp * val
        a_obs = x["a"] if x else 0; b_obs = x["b"] if x else 0
        obsA += a_obs; obsB += b_obs
        s_mod_sem_delta = m["base"] + m["q"] * (t - m["base"])
        n_obs = a_obs + b_obs
        # dentro do município: mistura o que já foi apurado nele com o modelo
        w_obs = n_obs / (n_obs + PRIOR_N0) if n_obs else 0.0
        s_obs = a_obs / n_obs if n_obs else 0.0
        d = por_uf.setdefault(uf, {"a_obs": 0.0, "b_obs": 0.0, "v": 0.0, "vs": 0.0, "vq": 0.0, "vb": 0.0, "wmod": 0.0})
        d["a_obs"] += a_obs; d["b_obs"] += b_obs
        # parte do modelo (sujeita a erro de t e delta) e parte observada no próprio município
        d["v"] += v_rest
        d["vs"] += v_rest * (w_obs * s_obs + (1 - w_obs) * s_mod_sem_delta)
        d["vq"] += v_rest * (1 - w_obs) * m["q"]          # sensibilidade a t
        d["wmod"] += v_rest * (1 - w_obs)                  # sensibilidade a delta e ao erro comum
    frac_apur = eleit_apur / max(1, eleit_tot)

    def total(dt, dlt, sis):
        a = b = 0.0; ufs = {}
        for uf, d in por_uf.items():
            ajuste = delta.get(uf, 0.0) + dlt.get(uf, 0.0) + sis
            a_rest = d["vs"] + d["vq"] * dt + d["wmod"] * ajuste
            a_rest = min(max(a_rest, 0.0), d["v"])
            au = d["a_obs"] + a_rest; bu = d["b_obs"] + (d["v"] - a_rest)
            ufs[uf] = au / (au + bu) if au + bu else 0.5
            a += au; b += bu
        return a, b, ufs

    a_c, b_c, ufs_c = total(0.0, {}, 0.0)
    rnd = random.Random(semente)
    sig_sis = SIGMA_SIS0 * (1 - frac_apur) ** 0.5
    amostras = []; vit = 0
    for _ in range(sims):
        dt = rnd.gauss(0, info["se_t"])
        dlt = {uf: rnd.gauss(0, info["se_uf"].get(uf, TAU_UF)) for uf in por_uf}
        a, b, _ = total(dt, dlt, rnd.gauss(0, sig_sis))
        p = a / (a + b); amostras.append(p); vit += p > 0.5
    amostras.sort()
    q = lambda f: amostras[min(len(amostras) - 1, int(f * len(amostras)))]
    return {"pA": a_c / (a_c + b_c), "lo90": q(0.05), "hi90": q(0.95), "chanceA": vit / sims,
            "votosA": round(a_c), "votosB": round(b_c), "t": t, "se_t": info["se_t"], "munis": info["n"],
            "apurado_eleitorado": frac_apur, "obsA": obsA, "obsB": obsB, "uf": ufs_c}
