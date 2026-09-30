#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export OPENBENCH_GCP_VLLM_BASE_URL="${OPENBENCH_GCP_VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export OPENBENCH_GCP_VLLM_MODEL="${OPENBENCH_GCP_VLLM_MODEL:-unsloth/GLM-4.7-Flash-FP8-Dynamic}"

results_dir="$ROOT/results"
results_path="$results_dir/thesis-opencode-glm-4.7-flash.jsonl"
mkdir -p "$results_dir"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is not on PATH" >&2
  exit 1
fi

curl_args=(-fsS "${OPENBENCH_GCP_VLLM_BASE_URL%/}/models")
if [[ -n "${OPENBENCH_GCP_VLLM_API_KEY:-}" ]]; then
  curl_args=(-fsS -H "Authorization: Bearer ${OPENBENCH_GCP_VLLM_API_KEY}" "${OPENBENCH_GCP_VLLM_BASE_URL%/}/models")
fi
if ! curl "${curl_args[@]}" >/dev/null; then
  echo "Cannot reach ${OPENBENCH_GCP_VLLM_BASE_URL}. Open the IAP tunnel first." >&2
  echo "  gcloud compute ssh thesis-vllm-glm47 --project=nyu-rdg-fy26-js11531-a68d --zone=us-central1-a --tunnel-through-iap -- -N -L 8000:127.0.0.1:8000" >&2
  exit 1
fi

if command -v obench >/dev/null 2>&1; then
  runner=(obench)
else
  runner=(python3 -m obench)
fi

echo "Writing rows to ${results_path}"
"${runner[@]}" legacy run \
  --exec local \
  --harness opencode \
  --model gcp-vllm/glm-4.7-flash \
  --task make-ci-green,add-feature,misleading-error \
  --results-path "$results_path" \
  --timeout 7200 \
  --allow-version-drift
