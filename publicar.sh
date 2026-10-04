#!/usr/bin/env bash
# Publica o painel: carimba a versão no index.html e no versao.txt, faz commit e push.
# Uso: ./publicar.sh "mensagem do commit"   (rodar dentro da pasta do repositório)
set -e
VERSAO=$(date -u +%Y%m%d-%H%M%S)
sed -i "s/^const VERSAO = \"[^\"]*\";/const VERSAO = \"$VERSAO\";/" index.html
grep -q "const VERSAO = \"$VERSAO\";" index.html || { echo "não consegui carimbar a versão"; exit 1; }
printf "%s\n" "$VERSAO" > versao.txt
git add -A
git commit -q -m "$1"
git pull -q --rebase
git push -q
echo "publicado: versão $VERSAO"
