"""Gravador do histórico da apuração para o GitHub Actions.

Lê o arquivo de Presidente/Brasil do TSE a cada 30 s e, quando a totalização muda,
acrescenta um ponto em historico-<eleicao>.json dentro de DADOS_DIR e envia (git push)
para o branch "dados". O painel publicado lê esse arquivo para mostrar a curva completa.

Variáveis de ambiente:
  DADOS_DIR  pasta (worktree do branch dados) onde o JSON é gravado
  HORAS      quanto tempo rodar antes de encerrar (padrão 5.8; o limite do Actions é 6 h)
Encerra antes se a totalização terminar. Sai com código 3 quando o tempo acaba e a
apuração ainda não terminou, para o workflow disparar a próxima rodada.
"""
import json, os, subprocess, sys, time, datetime, threading
from apuracao_servidor import BASE, descobrir_eleicao, get_resultado, ponto, ponto_nacional, log

DADOS_DIR = os.environ.get("DADOS_DIR", "dados")
HORAS = float(os.environ.get("HORAS", "5.8"))
INTERVALO = 30
PUSH_MIN = 45  # segundos entre pushes
# previsão do 2º turno: enviada ao contador (Cloudflare), que repassa a todos os painéis abertos
PREVISAO_URL = os.environ.get("PREVISAO_URL", "https://painel-online.pedro0-75c.workers.dev/previsao")
PREVISAO_TOKEN = os.environ.get("PREVISAO_TOKEN", "")
PREVISAO_INTERVALO = 25


def primeiro_turno_de(cd2):
    """Código da eleição do 1º turno cujo 2º turno é cd2 (campo cdt2 da configuração do TSE)."""
    from apuracao_servidor import get_json
    cfg = get_json(BASE + "comum/config/ele-c.json")
    for pl in cfg.get("pl", []):
        for e in pl.get("e", []):
            if str(e.get("cdt2")) == str(cd2):
                return e["cd"]
    return None


def eleicao_forcada(cd):
    """Para testes: usa a eleição de código cd (variável ELEICAO) em vez da escolhida pela data."""
    from apuracao_servidor import get_json
    cfg = get_json(BASE + "comum/config/ele-c.json")
    for pl in cfg.get("pl", []):
        for e in pl.get("e", []):
            if str(e.get("cd")) == str(cd):
                d, m, a = (int(x) for x in pl["dt"].split("/"))
                return (datetime.date(a, m, d), e["cd"], pl["c"], e.get("t"))
    return None


def envia_previsao(p):
    import urllib.request
    if not PREVISAO_TOKEN:
        return
    req = urllib.request.Request(PREVISAO_URL, data=json.dumps(p, separators=(",", ":")).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + PREVISAO_TOKEN, "Content-Type": "application/json",
                                          "User-Agent": "painel-apuracao/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


# a previsão roda numa linha de execução à parte: baixar milhares de municípios leva minutos no começo
# da apuração e não pode atrasar a gravação da curva. LOCK protege os arquivos durante o git add/commit.
LOCK = threading.Lock()


class Previsor(threading.Thread):
    def __init__(self, ciclo, cd):
        super().__init__(daemon=True)
        self.ciclo, self.cd = ciclo, cd
        self.ponto = {"pst": 0.0, "ht": "", "dt": ""}   # último ponto do TSE, atualizado pela linha principal
        self.novos = False                               # há previsão nova gravada para enviar ao GitHub
        self.parar = False

    def run(self):
        coletor = None
        while not self.parar:
            inicio = time.time()
            try:
                if coletor is None:
                    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "previsao"))
                    from coletor import Coletor
                    coletor = Coletor(self.ciclo, self.cd, primeiro_turno_de(self.cd))
                prev = coletor.ciclo_()
                pt = dict(self.ponto)
                prev.update({"pst_tse": pt["pst"], "ht_tse": pt["ht"], "dt_tse": pt["dt"]})
                try:
                    envia_previsao(prev)
                except Exception as err:
                    log("Falha ao enviar a previsão ao contador:", err)
                with LOCK:
                    arqp = os.path.join(DADOS_DIR, f"previsao-{self.cd}.json")
                    hp = json.load(open(arqp, encoding="utf-8")) if os.path.exists(arqp) else []
                    hp.append({k: prev.get(k) for k in ("calculado", "ht_tse", "pst_tse", "pA", "lo90", "hi90", "chanceA", "t", "municipios_apurados", "apurado_eleitorado", "A", "B", "votosA", "votosB")})
                    with open(arqp, "w", encoding="utf-8") as f:
                        json.dump(hp, f, separators=(",", ":"))
                    self.novos = True
                log(f"Previsão: A {prev['pA']*100:.2f}% ({prev['lo90']*100:.1f}–{prev['hi90']*100:.1f}), chance {prev['chanceA']*100:.0f}%, "
                    f"{prev['municipios_apurados']} municípios ({prev['atualizados_no_ciclo']} novos, {time.time()-inicio:.0f} s)")
            except Exception as err:
                log("Falha na previsão:", err)
            time.sleep(max(5, PREVISAO_INTERVALO - (time.time() - inicio)))


def git(*args):
    return subprocess.run(["git", "-C", DADOS_DIR, *args], capture_output=True, text=True)


def publicar(msg):
    with LOCK:
        git("add", "-A")
        if git("diff", "--cached", "--quiet").returncode == 0:
            return
        git("commit", "-q", "-m", msg)
    for _ in range(3):
        if git("push", "-q", "origin", "HEAD:dados").returncode == 0:
            return
        git("pull", "-q", "--rebase", "origin", "dados")
    log("Falha no push; tento de novo no próximo ponto")


def main():
    fim = time.time() + HORAS * 3600
    ele, ultimo_push, pendente, final = None, 0, False, False
    previsor = None
    while time.time() < fim:
        try:
            if ele is None:
                ele = eleicao_forcada(os.environ["ELEICAO"]) if os.environ.get("ELEICAO") else descobrir_eleicao()
                if ele:
                    log(f"Eleição {ele[1]} ({ele[3]}º turno, {ele[0]:%d/%m/%Y})")
            if ele:
                cd, ciclo = ele[1], ele[2]
                novo, d = ponto_nacional(ciclo, cd)
                arq = os.path.join(DADOS_DIR, f"historico-{cd}.json")
                hist = json.load(open(arq, encoding="utf-8")) if os.path.exists(arq) else []
                ult = hist[-1] if hist else None
                if not ult or (ult["ht"], ult["st"]) != (novo["ht"], novo["st"]):
                    hist.append(novo)
                    with open(arq, "w", encoding="utf-8") as f:
                        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
                    pendente = True
                    log(f"Novo ponto: {novo['pst']:.2f}% das seções (totalização {novo['ht']}) · {len(hist)} pontos")
                # previsão (só no 2º turno), em paralelo
                if ele[3] == "2":
                    if previsor is None:
                        previsor = Previsor(ciclo, cd)
                        previsor.start()
                    previsor.ponto = {"pst": novo["pst"], "ht": novo["ht"], "dt": novo["dt"]}
                    if previsor.novos:
                        previsor.novos, pendente = False, True
                final = d.get("tf") == "s" and novo["pst"] >= 100
                if pendente and (time.time() - ultimo_push >= PUSH_MIN or final):
                    publicar(f"Histórico {cd}: {novo['pst']:.2f}% das seções às {novo['ht']}")
                    ultimo_push, pendente = time.time(), False
                if final:
                    if previsor:
                        previsor.parar = True
                    log("Totalização concluída; encerrando.")
                    return 0
        except Exception as err:
            log("Falha ao ler o TSE:", err)
        time.sleep(INTERVALO)
    if pendente:
        publicar("Histórico: últimos pontos da rodada")
    return 3


if __name__ == "__main__":
    sys.exit(main())
