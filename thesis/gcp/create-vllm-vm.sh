#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-nyu-rdg-fy26-js11531-a68d}"
VM_NAME="${VM_NAME:-thesis-vllm-glm47}"
MACHINE_TYPE="${MACHINE_TYPE:-g2-standard-24}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-2}"
IMAGE_PROJECT="${IMAGE_PROJECT:-deeplearning-platform-release}"
IMAGE_FAMILY="${IMAGE_FAMILY:-common-cu129-ubuntu-2204-nvidia-580}"
BOOT_DISK_SIZE="${BOOT_DISK_SIZE:-200GB}"
VLLM_MODEL="${VLLM_MODEL:-unsloth/GLM-4.7-Flash-FP8-Dynamic}"
VLLM_PORT="${VLLM_PORT:-8000}"
VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-32768}"
VLLM_DTYPE="${VLLM_DTYPE:-bfloat16}"
VLLM_TOOL_CALL_PARSER="${VLLM_TOOL_CALL_PARSER:-glm47}"
VLLM_REASONING_PARSER="${VLLM_REASONING_PARSER:-glm45}"
VLLM_VERSION="${VLLM_VERSION:-0.30.0}"
VLLM_EXTRA_ARGS="${VLLM_EXTRA_ARGS:-}"

SHARED_NETWORK="nyu-rdg-fy26-js11531-net"
THESIS_NETWORK="thesis-vpc"
THESIS_SUBNET="thesis-subnet-usc1"
THESIS_SUBNET_RANGE="${SUBNET_RANGE:-10.10.0.0/20}"
THESIS_ROUTER="thesis-router"
THESIS_NAT="thesis-nat"
THESIS_REGION="us-central1"
SUBNET="${SUBNET:-}"

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

if [[ -n "${ZONES:-}" ]]; then
  read -r -a zone_list <<< "$ZONES"
elif [[ -n "${ZONE:-}" ]]; then
  zone_list=("$ZONE")
else
  zone_list=(us-central1-a us-central1-b us-central1-c)
fi
if [[ "${#zone_list[@]}" -eq 0 ]]; then
  refuse "ZONES is empty"
fi
ZONE="${zone_list[0]}"

if [[ -z "${NO_ADDRESS+x}" ]]; then
  NO_ADDRESS=1
fi
case "$NO_ADDRESS" in
  1|true|TRUE|yes|YES) no_address=1 ;;
  0|false|FALSE|no|NO|"") no_address=0 ;;
  *) refuse "NO_ADDRESS must be 1 or 0" ;;
esac

provision_thesis_network=0
if [[ -z "${NETWORK:-}" || "$NETWORK" == "$THESIS_NETWORK" ]]; then
  NETWORK="$THESIS_NETWORK"
  SUBNET="${SUBNET:-$THESIS_SUBNET}"
  provision_thesis_network=1
fi

if [[ ! "$VM_NAME" =~ ^thesis-[A-Za-z0-9-]+$ ]]; then
  refuse "VM name ${VM_NAME} must start with thesis- and use only letters, digits, and hyphens"
fi
for zone in "${zone_list[@]}"; do
  if [[ ! "$zone" =~ ^us-central1-[a-z]$ ]]; then
    refuse "zone ${zone} must be a us-central1 zone such as us-central1-a"
  fi
done
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
if [[ "$NETWORK" == "$SHARED_NETWORK" || "$NETWORK" == "default" ]]; then
  refuse "network ${NETWORK} is not available. Leave NETWORK unset to create ${THESIS_NETWORK}"
fi
if [[ ! "$NETWORK" =~ ^[a-z][-a-z0-9]{0,62}$ ]]; then
  refuse "NETWORK ${NETWORK} is not a VPC network name"
fi
if [[ -n "$SUBNET" && ! "$SUBNET" =~ ^[a-z][-a-z0-9]{0,62}$ ]]; then
  refuse "SUBNET ${SUBNET} is not a subnet name"
fi
if [[ "$provision_thesis_network" -eq 1 ]]; then
  for name in "$NETWORK" "$SUBNET" "$THESIS_ROUTER" "$THESIS_NAT"; do
    if [[ ! "$name" =~ ^thesis-[A-Za-z0-9-]+$ ]]; then
      refuse "will not create ${name}. Thesis network resources must start with thesis-"
    fi
  done
  if [[ "$SUBNET" == "$THESIS_SUBNET" && ! "$THESIS_SUBNET_RANGE" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
    refuse "SUBNET_RANGE must be an IPv4 CIDR"
  fi
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
Environment=PATH=/opt/thesis-vllm/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
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
  "--metadata=install-nvidia-driver=True,block-project-ssh-keys=TRUE,thesis-vllm-model=$(printf '%s' "$VLLM_MODEL")"
  "--metadata-from-file=startup-script=${startup_file}"
)
if [[ -n "${HF_TOKEN:-}" ]]; then
  token_file="$(mktemp)"
  printf '%s' "$HF_TOKEN" >"$token_file"
  chmod 600 "$token_file"
  metadata_args+=("--metadata-from-file=thesis-hf-token=${token_file}")
fi

build_create_cmd() {
  local zone="$1"
  create_cmd=(
    gcloud compute instances create "$VM_NAME"
    --project="$PROJECT"
    --zone="$zone"
    --machine-type="$MACHINE_TYPE"
    --maintenance-policy=TERMINATE
    --image-project="$IMAGE_PROJECT"
    --image-family="$IMAGE_FAMILY"
    --boot-disk-size="$BOOT_DISK_SIZE"
    --boot-disk-type=pd-balanced
    --network="$NETWORK"
    --tags="$NETWORK_TAG"
  )
  if [[ -n "$SUBNET" ]]; then
    create_cmd+=(--subnet="$SUBNET")
  fi
  if [[ "$no_address" -eq 1 ]]; then
    create_cmd+=(--no-address)
  fi
  create_cmd+=("${metadata_args[@]}")
}

network_create_cmd=(
  gcloud compute networks create "$THESIS_NETWORK"
  --project="$PROJECT"
  --subnet-mode=custom
  --bgp-routing-mode=regional
)
subnet_create_cmd=(
  gcloud compute networks subnets create "$THESIS_SUBNET"
  --project="$PROJECT"
  --network="$THESIS_NETWORK"
  --region="$THESIS_REGION"
  --range="$THESIS_SUBNET_RANGE"
)
router_create_cmd=(
  gcloud compute routers create "$THESIS_ROUTER"
  --project="$PROJECT"
  --network="$THESIS_NETWORK"
  --region="$THESIS_REGION"
)
nat_create_cmd=(
  gcloud compute routers nats create "$THESIS_NAT"
  --project="$PROJECT"
  --router="$THESIS_ROUTER"
  --region="$THESIS_REGION"
  --auto-allocate-nat-external-ips
  --nat-all-subnet-ip-ranges
)
allow_cmd=(
  gcloud compute firewall-rules create "$ALLOW_IAP_RULE"
  --project="$PROJECT"
  --network="$NETWORK"
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
  --network="$NETWORK"
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

is_capacity_error() {
  local text
  text="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  [[ "$text" == *zone_resource_pool_exhausted* ]] && return 0
  [[ "$text" == *"does not have enough resources"* ]] && return 0
  [[ "$text" == *"not enough resources"* ]] && return 0
  [[ "$text" == *stockout* ]] && return 0
  return 1
}

if [[ "$dry_run" -eq 1 ]]; then
  if [[ "$provision_thesis_network" -eq 1 ]]; then
    print_cmd "${network_create_cmd[@]}"
    if [[ "$SUBNET" == "$THESIS_SUBNET" ]]; then
      print_cmd "${subnet_create_cmd[@]}"
    fi
    print_cmd "${router_create_cmd[@]}"
    print_cmd "${nat_create_cmd[@]}"
  fi
  print_cmd "${allow_cmd[@]}"
  print_cmd "${deny_cmd[@]}"
  echo "# zones: ${zone_list[*]}"
  build_create_cmd "${zone_list[0]}"
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

for zone in "${zone_list[@]}"; do
  if gcloud compute instances describe "$VM_NAME" --project="$PROJECT" --zone="$zone" >/dev/null 2>&1; then
    refuse "${VM_NAME} already exists in ${zone}. Stop or delete it with thesis/gcp/teardown-vllm-vm.sh before creating it again"
  fi
done

gcloud_quiet() {
  gcloud "$@" >/dev/null 2>&1
}

if [[ "$provision_thesis_network" -eq 1 ]]; then
  if ! gcloud_quiet compute networks describe "$THESIS_NETWORK" --project="$PROJECT"; then
    "${network_create_cmd[@]}"
  fi
  if [[ "$SUBNET" == "$THESIS_SUBNET" ]] && ! gcloud_quiet compute networks subnets describe "$THESIS_SUBNET" --project="$PROJECT" --region="$THESIS_REGION"; then
    "${subnet_create_cmd[@]}"
  fi
  if ! gcloud_quiet compute routers describe "$THESIS_ROUTER" --project="$PROJECT" --region="$THESIS_REGION"; then
    "${router_create_cmd[@]}"
  fi
  if ! gcloud_quiet compute routers nats describe "$THESIS_NAT" --router="$THESIS_ROUTER" --project="$PROJECT" --region="$THESIS_REGION"; then
    "${nat_create_cmd[@]}"
  fi
fi

ensure_firewall() {
  local name="$1"
  shift
  local net
  if net="$(gcloud compute firewall-rules describe "$name" --project="$PROJECT" --format='value(network)' 2>/dev/null)"; then
    case "$net" in
      */networks/"$NETWORK"|"$NETWORK") return 0 ;;
      *) refuse "firewall rule ${name} is on ${net}, not ${NETWORK}. Delete that rule by hand before creating this VM" ;;
    esac
  fi
  "$@"
}

ensure_firewall "$ALLOW_IAP_RULE" "${allow_cmd[@]}"
ensure_firewall "$DENY_INGRESS_RULE" "${deny_cmd[@]}"

create_instance_in_zone() {
  local zone="$1"
  local errfile status err
  errfile="$(mktemp)"
  build_create_cmd "$zone"
  set +e
  "${create_cmd[@]}" 2>"$errfile"
  status=$?
  set -e
  if [[ "$status" -eq 0 ]]; then
    rm -f "$errfile"
    return 0
  fi
  err="$(cat "$errfile")"
  rm -f "$errfile"
  printf '%s\n' "$err" >&2
  if is_capacity_error "$err"; then
    echo "no capacity in ${zone}" >&2
    return 2
  fi
  return 1
}

created_zone=""
for zone in "${zone_list[@]}"; do
  status=0
  create_instance_in_zone "$zone" || status=$?
  if [[ "$status" -eq 0 ]]; then
    created_zone="$zone"
    break
  fi
  if [[ "$status" -eq 2 ]]; then
    continue
  fi
  exit 1
done
if [[ -z "$created_zone" ]]; then
  refuse "no zone in ${zone_list[*]} had capacity for ${MACHINE_TYPE}"
fi

echo "Created ${VM_NAME} in ${created_zone}."
echo "vLLM listens on 127.0.0.1:${VLLM_PORT} inside the VM. The VM has no external address."
echo "SSH keys stay on this instance because block-project-ssh-keys=TRUE. Do not run gcloud compute config-ssh."
echo "Open an IAP tunnel from the operator machine:"
echo "  gcloud compute ssh ${VM_NAME} --project=${PROJECT} --zone=${created_zone} --tunnel-through-iap -- -N -L ${VLLM_PORT}:127.0.0.1:${VLLM_PORT}"
