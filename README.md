# Apuração Presidente 2026

Painel para acompanhar a apuração da eleição para Presidente da República de 2026 em tempo real, com dados públicos do TSE.

**Ver o painel:** https://pedreirorr.github.io/painel-eleicao-2026/

**Direto na aba Goiás:** https://pedreirorr.github.io/painel-eleicao-2026/#goias

## O que mostra

- Percentual de seções totalizadas e hora da última totalização do TSE
- Votos e % dos votos válidos de cada candidato, com a média das pesquisas como referência
- Comparecimento, abstenção, brancos, nulos e anulados
- Evolução da apuração (por horário ou por % apurado) e diferença entre 1º e 2º colocados
- Trajetória da média das pesquisas (abril a 3 de outubro de 2026)
- Resultado por estado e no exterior
- Aba **Goiás** (`#goias`): Governador, Senado, Deputado Federal e Deputado Estadual, com busca de candidatos

## Como funciona

A página é um único `index.html`. O navegador de cada visitante lê, a cada 30 segundos, os arquivos públicos de divulgação do TSE em `resultados.tse.jus.br`. Não há servidor intermediário.

A curva de evolução vem do histórico público gravado pelo workflow **Histórico da apuração** (GitHub Actions), que lê o TSE a cada 30 s durante a apuração e salva `historico-<eleição>.json` no branch `dados`. Quem abre a página já vê a curva desde o início, somada às leituras feitas pela própria página.

O workflow roda sozinho nos dias de votação (agendado para 16h40 de Brasília) e se reagenda a cada 6 h até a totalização terminar. Também pode ser iniciado manualmente na aba *Actions*.

Para gravar um histórico no seu computador, rode localmente:

```
python apuracao_servidor.py
```

e abra `http://localhost:8765/index.html`.

Para ver o simulado oficial do TSE (dados fictícios), acrescente `?sim=1` ao endereço.

## Fontes

- Resultados: [TSE — resultados.tse.jus.br](https://resultados.tse.jus.br)
- Pesquisas: levantamentos registrados no TSE e compilados na [Wikipedia](https://en.wikipedia.org/wiki/Opinion_polling_for_the_2026_Brazilian_presidential_election), convertidos para votos válidos
