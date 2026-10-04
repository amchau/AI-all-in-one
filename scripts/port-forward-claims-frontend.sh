#!/usr/bin/env bash
set -euo pipefail

kubectl -n ai-platform port-forward svc/claims-frontend 4173:8080