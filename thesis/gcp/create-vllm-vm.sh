#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-nyu-rdg-fy26-js11531-a68d}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-thesis-vllm-glm47}"
MACHINE_TYPE="${MACHINE_TYPE:-g2-standard-24}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-2}"
IMAGE_PROJECT="${IMAGE_PROJECT:-deeplearning-platform-release}"
IMAGE_FAMILY="${IMAGE_FAMILY:-common-cu129-ubuntu-2204-nvidia-580}"
BOOT_DISK_SIZE="${BOOT_DISK_SIZE:-200GB}"
VLLM_MODEL="${VLLM_MODEL:-unsloth/GLM-4.7-Flash-FP8-Dynamic}"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
VLLM_DTYPE="${VLLM_DTYPE:-bfloat16}"
VLLM_TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-glm47}"
VLLM_REASONING_PARSER="${VLLM_REASONING_PARSER:-glm45}"
VLLM_VERSION="${VLLM_VERSION:-0.30.0}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"

ALLOW_IAP_RULE="thesis-allow-iap-ssh"
DENY_INGRESS_RULE="thesis-deny-ingress"
NETWORK_TAG="thesis-iap"
IAP_SOURCE="35.235.240.0/20"

dry_run=0
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=1
elif [[ -n "${1:-}" ]]; then
  echo "usage: $0 [--dry-run]" >&2
  exit 2
fi

refuse() {
  echo "refusing: $*" >&2
  exit 1
}

if [[ ! "$VM_NAME" =~ ^thesis-[A-Za-z0-9-]+$ ]]; then
  refuse "VM name ${VM_NAME} must start with thesis- and use only letters, digits, and hyphens"
fi
if [[ ! "$ZONE" =~ ^us-central1-[a-z]$ ]]; then
  refuse "zone ${ZONE} must be a us-central1 zone such as us-central1-a"
fi
if [[ ! "$MACHINE_TYPE" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)+$ ]]; then
  refuse "machine type ${MACHINE_TYPE} is not a Compute Engine machine type"
fi
if [[ ! "$TENSOR_PARALLEL_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  refuse "TENSOR_PARALLEL_SIZE must be a positive integer"
fi
if [[ ! "$VLLM_PORT" =~ ^[0-9]+$ ]]; then
  refuse "VLLM_PORT must be a number"
fi
if [[ ! "$VLLM_MAX_MODEL_LEN" =~ ^[0-9]+$ ]]; then
  refuse "VLLM_MAX_MODEL_LEN must be a number"
fi
if [[ ! "$VLLM_MODEL" =~ ^[A-Za-z0-9_./:-]+$ ]]; then
  refuse "VLLM_MODEL contains characters this script will not embed"
fi
if [[ ! "$VLLM_DTYPE" =~ ^(auto|bfloat16|float16|float32)$ ]]; then
  refuse "VLLM_DTYPE must be auto, bfloat16, float16, or float32"
fi
if [[ ! "$VLLM_TOOL_CALL_PARSER" =~ ^[A-Za-z0-9_-]+$ ]]; then
  refuse "VLLM_TOOL_CALL_PARSER contains characters this script will not embed"
fi
if [[ ! "$VLLM_REASONING_PARSER" =~ ^[A-Za-z0-9_-]+$ ]]; then
  refuse "VLLM_REASONING_PARSER contains characters this script will not embed"
fi
if [[ ! "$VLLM_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  refuse "VLLM_VERSION must be a dotted release such as 0.30.0"
fi

extra_quoted=""
if [[ -n "$VLLM_EXTRA_ARGS" ]]; then
  extra_words=()
  IFS=' ' read -r -a extra_words <<< "$VLLM_EXTRA_ARGS"
  for word in "${extra_words[@]}"; do
    if [[ -z "$word" ]]; then
      continue
    fi
    extra_quoted+=" $(printf '%q' "$word")"
  done
fi

startup_file="$(mktemp)"
token_file=""
cleanup() {
  rm -f "$startup_file"
  if [[ -n "$token_file" ]]; then
    rm -f "$token_file"
  fi
}
trap cleanup EXIT

cat >"$startup_file" <<EOF
#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/thesis-vllm.log) 2>&1
echo "thesis vllm startup \$(date -Is)"

for _ in \$(seq 1 60); do
  if nvidia-smi >/dev/null 2>&1; then
    break
  fi
  sleep 10
done
nvidia-smi

if [[ ! -x /opt/thesis-vllm/bin/vllm ]]; then
  if ! python3 -m venv /opt/thesis-vllm; then
    apt-get update
    apt-get install -y python3 python3-venv python3-pip
    python3 -m venv /opt/thesis-vllm
  fi
  /opt/thesis-vllm/bin/pip install -U pip
  /opt/thesis-vllm/bin/pip install "vllm==$(printf '%q' "$VLLM_VERSION")"
fi

if curl -fsS -H "Metadata-Flavor: Google" \\
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/thesis-hf-token \\
  > /opt/thesis-vllm/hf-token; then
  chmod 600 /opt/thesis-vllm/hf-token
else
  rm -f /opt/thesis-vllm/hf-token
fi

cat > /opt/thesis-vllm/serve.sh <<'SERVE'
#!/bin/bash
set -euo pipefail
export HF_HOME=/opt/thesis-vllm/hf
if [[ -s /opt/thesis-vllm/hf-token ]]; then
  export HF_TOKEN="\$(cat /opt/thesis-vllm/hf-token)"
  export HUGGING_FACE_HUB_TOKEN="\$HF_TOKEN"
fi
exec /opt/thesis-vllm/bin/vllm serve $(printf '%q' "$VLLM_MODEL") \\
  --host 127.0.0.1 \\
  --port $(printf '%q' "$VLLM_PORT") \\
  --dtype $(printf '%q' "$VLLM_DTYPE") \\
  --tensor-parallel-size $(printf '%q' "$TENSOR_PARALLEL_SIZE") \\
  --max-model-len $(printf '%q' "$VLLM_MAX_MODEL_LEN") \\
  --gpu-memory-utilization 0.90 \\
  --enable-auto-tool-choice \\
  --tool-call-parser $(printf '%q' "$VLLM_TOOL_CALL_PARSER") \\
  --reasoning-parser $(printf '%q' "$VLLM_REASONING_PARSER") \\
  --served-model-name $(printf '%q' "$VLLM_MODEL")${extra_quoted}
SERVE
chmod 755 /opt/thesis-vllm/serve.sh

cat > /etc/systemd/system/thesis-vllm.service <<'UNIT'
[Unit]
Description=thesis vLLM OpenAI server
After=network-online.target

[Service]
Type=simple
ExecStart=/opt/thesis-vllm/serve.sh
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now thesis-vllm.service
EOF

metadata_args=(
  "--metadata=install-nvidia-driver=True,thesis-vllm-model=$(printf '%s' "$VLLM_MODEL")"
  "--metadata-from-file=startup-script=${startup_file}"
)
if [[ -n "${HF_TOKEN:-}" ]]; then
  token_file="$(mktemp)"
  printf '%s' "$HF_TOKEN" >"$token_file"
  chmod 600 "$token_file"
  metadata_args+=("--metadata-from-file=thesis-hf-token=${token_file}")
fi

create_cmd=(
  gcloud compute instances create "$VM_NAME"
  --project="$PROJECT"
  --zone="$ZONE"
  --machine-type="$MACHINE_TYPE"
  --maintenance-policy=TERMINATE
  --image-project="$IMAGE_PROJECT"
  --image-family="$IMAGE_FAMILY"
  --boot-disk-size="$BOOT_DISK_SIZE"
  --boot-disk-type=pd-balanced
  --tags="$NETWORK_TAG"
  "${metadata_args[@]}"
)
allow_cmd=(
  gcloud compute firewall-rules create "$ALLOW_IAP_RULE"
  --project="$PROJECT"
  --direction=INGRESS
  --action=ALLOW
  --rules=tcp:22
  --source-ranges="$IAP_SOURCE"
  --target-tags="$NETWORK_TAG"
  --priority=900
)
deny_cmd=(
  gcloud compute firewall-rules create "$DENY_INGRESS_RULE"
  --project="$PROJECT"
  --direction=INGRESS
  --action=DENY
  --rules=all
  --source-ranges=0.0.0.0/0
  --target-tags="$NETWORK_TAG"
  --priority=1000
)

print_cmd() {
  printf '%q ' "$@"
  printf '\n'
}

if [[ "$dry_run" -eq 1 ]]; then
  print_cmd "${allow_cmd[@]}"
  print_cmd "${deny_cmd[@]}"
  redacted=()
  for arg in "${create_cmd[@]}"; do
    if [[ "$arg" == --metadata-from-file=thesis-hf-token=* ]]; then
      redacted+=("--metadata-from-file=thesis-hf-token=REDACTED")
    else
      redacted+=("$arg")
    fi
  done
  print_cmd "${redacted[@]}"
  echo "----- startup-script -----"
  cat "$startup_file"
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || refuse "gcloud is not on PATH"

if gcloud compute instances describe "$VM_NAME" --project="$PROJECT" --zone="$ZONE" >/dev/null 2>&1; then
  refuse "${VM_NAME} already exists. Stop or delete it with thesis/gcp/teardown-vllm-vm.sh before creating it again"
fi

if ! gcloud compute firewall-rules describe "$ALLOW_IAP_RULE" --project="$PROJECT" >/dev/null 2>&1; then
  "${allow_cmd[@]}"
fi
if ! gcloud compute firewall-rules describe "$DENY_INGRESS_RULE" --project="$PROJECT" >/dev/null 2>&1; then
  "${deny_cmd[@]}"
fi
"${create_cmd[@]}"

echo "Created ${VM_NAME} in ${ZONE}."
echo "vLLM listens on 127.0.0.1:${VLLM_PORT} inside the VM."
echo "Open an IAP tunnel from the operator machine:"
echo "  gcloud compute ssh ${VM_NAME} --project=${PROJECT} --zone=${ZONE} --tunnel-through-iap -- -N -L ${VLLM_PORT}:127.0.0.1:${VLLM_PORT}"
