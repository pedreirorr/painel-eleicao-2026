"""Servidor local do painel + gravador da apuração.

- Serve esta pasta em http://localhost:PORTA (abra painel-eleicao-2026.html por esse endereço).
- A cada 30 s lê o arquivo de Presidente/Brasil do TSE e, quando a totalização muda,
  acrescenta um ponto em historico-<eleicao>.json (o painel usa esse arquivo para a curva).

Uso: python apuracao_servidor.py [porta]   (padrão 8765)
"""
import json, os, sys, time, threading, urllib.request, datetime, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = "https://resultados.tse.jus.br/oficial/"
PASTA = os.path.dirname(os.path.abspath(__file__))
PORTA = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
INTERVALO = 30


def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "painel-apuracao/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get_resultado(url_json):
    """Lê a versão assinada (.jws), a mesma do site oficial, com ?nocache=; se falhar, usa o .json."""
    import base64
    try:
        url = url_json[:-5] + ".jws?nocache=" + str(int(time.time() * 1000))
        req = urllib.request.Request(url, headers={"User-Agent": "painel-apuracao/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            corpo = r.read().decode().strip().split(".")[1]
        return json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)).decode("utf-8"))
    except Exception:
        return get_json(url_json)


UFS = ["ac","al","am","ap","ba","ce","df","es","go","ma","mg","ms","mt","pa","pb","pe","pi","pr","rj","rn","ro","rr","rs","sc","se","sp","to","zz"]


def ponto_nacional(ciclo, cd):
    """Ponto do Brasil. Se a soma dos estados + exterior tiver mais seções totalizadas que o arquivo
    nacional (o TSE às vezes atrasa o br), usa a soma, com as mesmas regras de % do TSE."""
    from concurrent.futures import ThreadPoolExecutor
    url = lambda uf: f"{BASE}{ciclo}/{cd}/dados/{uf}/{uf}-c0001-e{int(cd):06d}-u.json"
    br = get_resultado(url("br"))
    novo = ponto(br)
    try:
        with ThreadPoolExecutor(8) as ex:
            ufs = list(ex.map(lambda u: get_resultado(url(u)), UFS))
    except Exception:
        return novo, br
    st = sum(inteiro(d["s"]["st"]) for d in ufs)
    if st <= novo["st"]:
        return novo, br
    votos = {}
    for d in ufs:
        for a in d["carg"][0].get("agr", []):
            for p in a.get("par", []):
                for c in p.get("cand", []):
                    votos[c["n"]] = votos.get(c["n"], 0) + inteiro(c.get("vap"))
    vv = sum(inteiro(d["v"].get("vv")) for d in ufs)
    ts = sum(inteiro(d["s"]["ts"]) for d in ufs)
    cand = {}
    for n, v in votos.items():
        pv = v / vv * 100 if vv else 0.0
        cand[n] = [v, 0.01 if (v > 0 and pv < 0.01) else round(pv, 9)]
    # horário: totalização mais recente entre os estados, ignorando horários no futuro (fuso local)
    agora = (datetime.datetime.utcnow() - datetime.timedelta(hours=3)).strftime("%Y%m%d%H:%M:%S")
    quando = lambda d: "".join(reversed((d.get("dt") or "").split("/"))) + (d.get("ht") or "")
    validos = [d for d in ufs if d.get("cdabr") != "zz" and quando(d) <= agora] or ufs
    ult = max(validos, key=quando)
    novo = {"dt": ult.get("dt"), "ht": ult.get("ht"), "pst": st / ts * 100 if ts else 0.0, "st": st, "vv": vv,
            "c": sum(inteiro(d["e"].get("c")) for d in ufs), "lido": datetime.datetime.now().isoformat(timespec="seconds"),
            "cand": cand, "somado_dos_estados": True}
    return novo, br


def descobrir_eleicao():
    """Mesma regra do painel: eleição federal de 2026 com cargo Presidente, a mais recente já iniciada."""
    cfg = get_json(BASE + "comum/config/ele-c.json")
    hoje = datetime.date.today()
    achadas = []
    for pl in cfg.get("pl", []):
        if pl.get("c") != "ele2026":
            continue
        d, m, a = (int(x) for x in pl["dt"].split("/"))
        for e in pl.get("e", []):
            br = next((x for x in e.get("abr", []) if x["cd"] == "br"), None)
            if br and any(c["cd"] == "1" for c in br.get("cp", [])):
                achadas.append((datetime.date(a, m, d), e["cd"], pl["c"], e.get("t")))
    if not achadas:
        return None
    achadas.sort()
    passadas = [x for x in achadas if x[0] <= hoje]
    return (passadas or achadas)[-1]


def dec(x):
    """Decimal no formato do TSE ("7,527528669" ou "100")."""
    try:
        return float(str(x if x not in (None, "") else 0).replace(",", "."))
    except ValueError:
        return 0.0


def inteiro(x):
    try:
        return int(str(x or 0).replace(".", ""))
    except ValueError:
        return 0


def ponto(d):
    cands = {}
    for a in d["carg"][0].get("agr", []):
        for p in a.get("par", []):
            for c in p.get("cand", []):
                cands[c["n"]] = [inteiro(c.get("vap")), dec(c.get("pvapn") or c.get("pvap"))]
    s, v, e = d.get("s", {}), d.get("v", {}), d.get("e", {})
    return {
        "dt": d.get("dt") or d.get("dg"), "ht": d.get("ht") or d.get("hg"),
        "pst": dec(s.get("pstn") or s.get("pst")), "st": inteiro(s.get("st")),
        "vv": inteiro(v.get("vv")), "c": inteiro(e.get("c")),
        "lido": datetime.datetime.now().isoformat(timespec="seconds"),
        "cand": cands,
    }


def gravador():
    ele, ultima_cfg = None, 0
    while True:
        try:
            if ele is None or time.time() - ultima_cfg > 600:
                achada = descobrir_eleicao()
                ultima_cfg = time.time()
                if achada and (ele is None or achada[1] != ele[1]):
                    ele = achada
                    log(f"Eleição {ele[1]} ({ele[3]}º turno, {ele[0]:%d/%m/%Y})")
            if ele:
                cd, ciclo = ele[1], ele[2]
                url = f"{BASE}{ciclo}/{cd}/dados/br/br-c0001-e{int(cd):06d}-u.json"
                novo, _ = ponto_nacional(ciclo, cd)
                arq = os.path.join(PASTA, f"historico-{cd}.json")
                hist = json.load(open(arq, encoding="utf-8")) if os.path.exists(arq) else []
                ult = hist[-1] if hist else None
                if not ult or (ult["ht"], ult["st"]) != (novo["ht"], novo["st"]):
                    hist.append(novo)
                    tmp = arq + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
                    os.replace(tmp, arq)
                    log(f"Novo ponto: {novo['pst']:.2f}% das seções (totalização {novo['ht']}) · {len(hist)} pontos")
        except Exception as err:
            log("Falha ao ler o TSE:", err)
        time.sleep(INTERVALO)


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=gravador, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), functools.partial(Handler, directory=PASTA))
    log(f"Painel em http://localhost:{PORTA}/index.html (ou painel-eleicao-2026.html)")
    srv.serve_forever()
