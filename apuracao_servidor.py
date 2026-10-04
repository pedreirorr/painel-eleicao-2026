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
                novo = ponto(get_json(url))
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
