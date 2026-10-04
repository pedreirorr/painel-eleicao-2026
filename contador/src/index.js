// Contador de dispositivos com o painel aberto.
// Cada painel mantém uma conexão WebSocket com a "sala" (um Durable Object) e informa um código
// aleatório do navegador (o mesmo em todas as abas). A sala conta os códigos diferentes entre as
// conexões abertas e avisa todos a cada mudança (no máximo a cada 2 s).
import { DurableObject } from "cloudflare:workers";

const ORIGENS = [
  "https://pedreirorr.github.io",
  "http://localhost:8765",
  "http://127.0.0.1:8765",
];
const CODIGO_VALIDO = /^[a-z0-9-]{8,40}$/;

// Vigia do TSE: enquanto houver painel aberto, lê a cada 10 s a "assinatura" (data|hora|seções) do
// arquivo de Presidente/Brasil e dos governadores dos estados com aba, e manda para todos os painéis.
// Mensagem de rede acorda a página mesmo quando o navegador desacelera os relógios da aba.
const TSE = "https://resultados.tse.jus.br/oficial/";
const UFS_GOV = ["go", "mg", "df", "sp"];
const CHECA_MS = 10000;
const pad = (v, n) => String(v).padStart(n, "0");
async function lerJWS(url) {
  const r = await fetch(url + "?nocache=" + Date.now(), { cf: { cacheTtl: 0 } });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const corpo = (await r.text()).trim().split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(corpo + "=".repeat((4 - corpo.length % 4) % 4));
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0))));
}
const assinatura = d => [d.dt || d.dg, d.ht || d.hg, d.s && d.s.st].join("|");
// mesma regra do painel: eleição de 2026 com Presidente (federal) e com Governador (estadual), turno mais recente já iniciado
function eleicoes(cfg) {
  const hoje = Date.now() + 86400000, fed = [], est = [];
  for (const pl of cfg.pl || []) {
    if (pl.c !== "ele2026") continue;
    const [d, m, a] = pl.dt.split("/").map(Number);
    if (new Date(a, m - 1, d).getTime() > hoje) continue;
    for (const e of pl.e || []) {
      const br = (e.abr || []).find(x => x.cd === "br");
      const cp = (br && br.cp) || [];
      if (cp.some(c => c.cd === "1")) fed.push({ cd: e.cd, t: e.t, ciclo: pl.c });
      if (cp.some(c => c.cd === "3")) est.push({ cd: e.cd, t: e.t, ciclo: pl.c });
    }
  }
  const ult = l => l.sort((a, b) => a.t - b.t)[l.length - 1] || null;
  return { fed: ult(fed), est: ult(est) };
}

export class Sala extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    // "ping" do painel é respondido pela própria Cloudflare, sem acordar a sala nem contar como requisição
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(req) {
    const d = new URL(req.url).searchParams.get("d") || "";
    const { 0: cliente, 1: servidor } = new WebSocketPair();
    // hibernação: conexões paradas não consomem tempo de execução
    this.ctx.acceptWebSocket(servidor);
    // conexões sem código válido contam como um dispositivo cada
    servidor.serializeAttachment({ d: CODIGO_VALIDO.test(d) ? d : crypto.randomUUID() });
    await this.agendarAviso();
    return new Response(null, { status: 101, webSocket: cliente });
  }

  abertas() {
    return this.ctx.getWebSockets().filter((ws) => ws.readyState === WebSocket.OPEN);
  }

  contagem(lista = this.abertas()) {
    const dispositivos = new Set(lista.map((ws) => ws.deserializeAttachment()?.d));
    return { online: dispositivos.size, conexoes: lista.length };
  }

  async contar() {
    return this.contagem();
  }

  async estadoTSE() {
    return { lido_ha_s: this.tseEm ? Math.round((Date.now() - this.tseEm) / 1000) : null, tse: this.tse || {} };
  }

  async agendarAviso() {
    // contagem nova sai em até 2 s (adianta o alarme do ciclo de 10 s, se preciso)
    const atual = await this.ctx.storage.getAlarm();
    if (atual == null || atual > Date.now() + 2000) await this.ctx.storage.setAlarm(Date.now() + 2000);
  }

  async checaTSE() {
    if (!this.cfg || Date.now() - this.cfgEm > 600000) {
      const r = await fetch(TSE + "comum/config/ele-c.json?nocache=" + Date.now());
      this.cfg = eleicoes(await r.json()); this.cfgEm = Date.now();
    }
    const { fed, est } = this.cfg, alvos = {};
    if (fed) alvos.br = `${TSE}${fed.ciclo}/${fed.cd}/dados/br/br-c0001-e${pad(fed.cd, 6)}-u.jws`;
    if (est) for (const uf of UFS_GOV) alvos[uf] = `${TSE}${est.ciclo}/${est.cd}/dados/${uf}/${uf}-c0003-e${pad(est.cd, 6)}-u.jws`;
    const res = await Promise.allSettled(Object.entries(alvos).map(async ([k, u]) => [k, assinatura(await lerJWS(u))]));
    this.tse = this.tse || {};
    for (const r of res) if (r.status === "fulfilled") this.tse[r.value[0]] = r.value[1];
    this.tseEm = Date.now();
  }

  async alarm() {
    const lista = this.abertas();
    if (!lista.length) return; // ninguém conectado: para de vigiar até alguém entrar
    if (!this.tseEm || Date.now() - this.tseEm >= CHECA_MS - 500) { try { await this.checaTSE(); } catch {} }
    const msg = JSON.stringify({ ...this.contagem(this.abertas()), tse: this.tse || {} });
    for (const ws of this.abertas()) { try { ws.send(msg); } catch {} }
    await this.ctx.storage.setAlarm(Date.now() + CHECA_MS);
  }

  async webSocketMessage(ws, msg) {
    // "conta": pedido explícito da contagem atual (usado ao conectar)
    if (msg === "conta") {
      try { ws.send(JSON.stringify({ ...this.contagem(), tse: this.tse || {} })); } catch {}
    }
  }

  async webSocketClose(ws, code) {
    try { ws.close(code === 1005 ? 1000 : code, "fim"); } catch {}
    await this.agendarAviso();
  }

  async webSocketError() {
    await this.agendarAviso();
  }
}

export default {
  async fetch(req, env) {
    const origem = req.headers.get("Origin") || "";
    const cors = ORIGENS.includes(origem) ? { "Access-Control-Allow-Origin": origem } : {};
    const sala = env.SALA.get(env.SALA.idFromName("painel-eleicao-2026"));

    if (req.headers.get("Upgrade") === "websocket") {
      if (!ORIGENS.includes(origem)) return new Response("Origem não permitida", { status: 403 });
      return sala.fetch(req);
    }
    if (new URL(req.url).pathname === "/online") {
      return Response.json(await sala.contar(), { headers: { ...cors, "Cache-Control": "no-store" } });
    }
    if (new URL(req.url).pathname === "/tse") {
      return Response.json(await sala.estadoTSE(), { headers: { ...cors, "Cache-Control": "no-store" } });
    }
    return new Response("Contador de dispositivos online do painel de apuração.", { headers: cors });
  },
};
