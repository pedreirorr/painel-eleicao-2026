# Apuração Presidente 2026

Painel para acompanhar a apuração da eleição para Presidente da República de 2026 em tempo real, com dados públicos do TSE.

**Ver o painel:** abra o link do GitHub Pages deste repositório.

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

A curva de evolução é montada no navegador a partir do momento em que a página é aberta. Para gravar o histórico completo, mesmo com a página fechada, rode localmente:

```
python apuracao_servidor.py
```

e abra `http://localhost:8765/index.html`.

Para ver o simulado oficial do TSE (dados fictícios), acrescente `?sim=1` ao endereço.

## Fontes

- Resultados: [TSE — resultados.tse.jus.br](https://resultados.tse.jus.br)
- Pesquisas: levantamentos registrados no TSE e compilados na [Wikipedia](https://en.wikipedia.org/wiki/Opinion_polling_for_the_2026_Brazilian_presidential_election), convertidos para votos válidos
