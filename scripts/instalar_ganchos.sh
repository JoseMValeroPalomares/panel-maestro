#!/usr/bin/env bash
# Instala el gancho pre-commit del repo (C-2) como enlace: si scripts/hooks/pre-commit cambia, no hay que reinstalar.
# No usa core.hooksPath: scripts/publicar.sh escribe su pre-push en la carpeta de ganchos de git y acabaría en el repo.
set -euo pipefail
cd "$(git -C "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" rev-parse --show-toplevel)"
hook=$(git rev-parse --git-path hooks/pre-commit)
if [[ -e $hook && ! -L $hook ]]; then
    mv -f "$hook" "$hook.bak-$(date +%Y%m%d-%H%M%S)"
    echo "El pre-commit que había queda en $hook.bak-*"
fi
ln -sfn "$PWD/scripts/hooks/pre-commit" "$hook"
git config blame.ignoreRevsFile .git-blame-ignore-revs
echo "Gancho instalado: lint + unitarios antes de cada commit (git commit --no-verify lo salta)."
