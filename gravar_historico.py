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
import json, os, subprocess, sys, time, datetime
from apuracao_servidor import BASE, descobrir_eleicao, get_resultado, ponto, log

DADOS_DIR = os.environ.get("DADOS_DIR", "dados")
HORAS = float(os.environ.get("HORAS", "5.8"))
INTERVALO = 30
PUSH_MIN = 45  # segundos entre pushes


def git(*args):
    return subprocess.run(["git", "-C", DADOS_DIR, *args], capture_output=True, text=True)


def publicar(msg):
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
    while time.time() < fim:
        try:
            if ele is None:
                ele = descobrir_eleicao()
                if ele:
                    log(f"Eleição {ele[1]} ({ele[3]}º turno, {ele[0]:%d/%m/%Y})")
            if ele:
                cd, ciclo = ele[1], ele[2]
                d = get_resultado(f"{BASE}{ciclo}/{cd}/dados/br/br-c0001-e{int(cd):06d}-u.json")
                novo = ponto(d)
                arq = os.path.join(DADOS_DIR, f"historico-{cd}.json")
                hist = json.load(open(arq, encoding="utf-8")) if os.path.exists(arq) else []
                ult = hist[-1] if hist else None
                if not ult or (ult["ht"], ult["st"]) != (novo["ht"], novo["st"]):
                    hist.append(novo)
                    with open(arq, "w", encoding="utf-8") as f:
                        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))
                    pendente = True
                    log(f"Novo ponto: {novo['pst']:.2f}% das seções (totalização {novo['ht']}) · {len(hist)} pontos")
                final = d.get("tf") == "s" and novo["pst"] >= 100
                if pendente and (time.time() - ultimo_push >= PUSH_MIN or final):
                    publicar(f"Histórico {cd}: {novo['pst']:.2f}% das seções às {novo['ht']}")
                    ultimo_push, pendente = time.time(), False
                if final:
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
