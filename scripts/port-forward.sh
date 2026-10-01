#!/usr/bin/env bash
set -euo pipefail

kubectl -n ai-platform port-forward svc/ai-api 8000:8000
