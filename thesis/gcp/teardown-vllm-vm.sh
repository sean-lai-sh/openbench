#!/usr/bin/env bash
# Stop or delete the thesis vLLM VM.
# The operator runs this script. Nothing in the repo invokes it.
#
# stop keeps the disk and the firewall rules.
# delete removes the named VM, then removes the thesis- firewall rules only
# when no other instance still carries the thesis-iap tag.

set -euo pipefail

PROJECT="${PROJECT:-nyu-rdg-fy26-js11531-a68d}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-thesis-vllm-glm47}"
ALLOW_IAP_RULE="thesis-allow-iap-ssh"
DENY_INGRESS_RULE="thesis-deny-ingress"
NETWORK_TAG="thesis-iap"

dry_run=0
mode=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    stop|delete)
      if [[ -n "$mode" ]]; then
        echo "usage: $0 [--dry-run] stop|delete" >&2
        exit 2
      fi
      mode="$arg"
      ;;
    *)
      echo "usage: $0 [--dry-run] stop|delete" >&2
      exit 2
      ;;
  esac
done
if [[ -z "$mode" ]]; then
  echo "usage: $0 [--dry-run] stop|delete" >&2
  exit 2
fi

if [[ ! "$VM_NAME" =~ ^thesis-[A-Za-z0-9-]+$ ]]; then
  echo "refusing: VM name ${VM_NAME} must start with thesis- and use only letters, digits, and hyphens" >&2
  exit 1
fi
if [[ ! "$ZONE" =~ ^us-central1-[a-z]$ ]]; then
  echo "refusing: zone ${ZONE} must be a us-central1 zone such as us-central1-a" >&2
  exit 1
fi

print_cmd() {
  printf '%q ' "$@"
  printf '\n'
}

stop_cmd=(
  gcloud compute instances stop "$VM_NAME"
  --project="$PROJECT"
  --zone="$ZONE"
)
delete_cmd=(
  gcloud compute instances delete "$VM_NAME"
  --project="$PROJECT"
  --zone="$ZONE"
  --quiet
)
firewall_cmd=(
  gcloud compute firewall-rules delete "$ALLOW_IAP_RULE" "$DENY_INGRESS_RULE"
  --project="$PROJECT"
  --quiet
)

if [[ "$dry_run" -eq 1 ]]; then
  if [[ "$mode" == "stop" ]]; then
    print_cmd "${stop_cmd[@]}"
  else
    print_cmd "${delete_cmd[@]}"
    echo "# firewall rules are deleted only when no other ${NETWORK_TAG} instance remains"
    print_cmd "${firewall_cmd[@]}"
  fi
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || {
  echo "refusing: gcloud is not on PATH" >&2
  exit 1
}

described="$(gcloud compute instances describe "$VM_NAME" \
  --project="$PROJECT" --zone="$ZONE" --format='value(name)')"
if [[ "$described" != "$VM_NAME" ]]; then
  echo "refusing: describe returned ${described}, not ${VM_NAME}" >&2
  exit 1
fi

if [[ "$mode" == "stop" ]]; then
  "${stop_cmd[@]}"
  echo "Stopped ${VM_NAME}."
  exit 0
fi

"${delete_cmd[@]}"
others="$(gcloud compute instances list \
  --project="$PROJECT" \
  --filter="tags.items=${NETWORK_TAG}" \
  --format='value(name)')"
if [[ -n "$others" ]]; then
  echo "Left firewall rules in place. Other ${NETWORK_TAG} instances remain:"
  echo "$others"
  exit 0
fi
"${firewall_cmd[@]}"
echo "Deleted ${VM_NAME} and the thesis- firewall rules."
