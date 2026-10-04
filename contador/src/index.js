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

  async agendarAviso() {
    if ((await this.ctx.storage.getAlarm()) == null) {
      await this.ctx.storage.setAlarm(Date.now() + 2000);
    }
  }

  async alarm() {
    const lista = this.abertas();
    const msg = JSON.stringify(this.contagem(lista));
    for (const ws of lista) {
      try { ws.send(msg); } catch {}
    }
  }

  async webSocketMessage(ws, msg) {
    // "conta": pedido explícito da contagem atual (usado ao conectar)
    if (msg === "conta") {
      try { ws.send(JSON.stringify(this.contagem())); } catch {}
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
    return new Response("Contador de dispositivos online do painel de apuração.", { headers: cors });
  },
};
