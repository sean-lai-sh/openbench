#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-nyu-rdg-fy26-js11531-a68d}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-thesis-vllm-glm47}"
ALLOW_IAP_RULE="thesis-allow-iap-ssh"
DENY_INGRESS_RULE="thesis-deny-ingress"
NETWORK_TAG="thesis-iap"
THESIS_NETWORK="thesis-vpc"
THESIS_SUBNET="thesis-subnet-usc1"
THESIS_ROUTER="thesis-router"
THESIS_NAT="thesis-nat"
THESIS_REGION="us-central1"

dry_run=0
keep_network=0
mode=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    --keep-network) keep_network=1 ;;
    stop|delete)
      if [[ -n "$mode" ]]; then
        echo "usage: $0 [--dry-run] [--keep-network] stop|delete" >&2
        exit 2
      fi
      mode="$arg"
      ;;
    *)
      echo "usage: $0 [--dry-run] [--keep-network] stop|delete" >&2
      exit 2
      ;;
  esac
done
if [[ -z "$mode" ]]; then
  echo "usage: $0 [--dry-run] [--keep-network] stop|delete" >&2
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
for name in "$ALLOW_IAP_RULE" "$DENY_INGRESS_RULE" "$THESIS_NETWORK" "$THESIS_SUBNET" "$THESIS_ROUTER" "$THESIS_NAT"; do
  if [[ ! "$name" =~ ^thesis-[A-Za-z0-9-]+$ ]]; then
    echo "refusing: ${name} is not a thesis- resource name" >&2
    exit 1
  fi
done

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
nat_delete_cmd=(
  gcloud compute routers nats delete "$THESIS_NAT"
  --project="$PROJECT"
  --router="$THESIS_ROUTER"
  --region="$THESIS_REGION"
  --quiet
)
router_delete_cmd=(
  gcloud compute routers delete "$THESIS_ROUTER"
  --project="$PROJECT"
  --region="$THESIS_REGION"
  --quiet
)
subnet_delete_cmd=(
  gcloud compute networks subnets delete "$THESIS_SUBNET"
  --project="$PROJECT"
  --region="$THESIS_REGION"
  --quiet
)
network_delete_cmd=(
  gcloud compute networks delete "$THESIS_NETWORK"
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
    if [[ "$keep_network" -eq 1 ]]; then
      echo "# --keep-network leaves ${THESIS_NETWORK}, ${THESIS_SUBNET}, ${THESIS_ROUTER}, and ${THESIS_NAT}"
    else
      echo "# thesis- network resources are deleted when no instance still uses ${THESIS_NETWORK}"
      print_cmd "${nat_delete_cmd[@]}"
      print_cmd "${router_delete_cmd[@]}"
      print_cmd "${subnet_delete_cmd[@]}"
      print_cmd "${network_delete_cmd[@]}"
    fi
  fi
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || {
  echo "refusing: gcloud is not on PATH" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "refusing: python3 is not on PATH" >&2
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

tagged="$(gcloud compute instances list --project="$PROJECT" --format=json | python3 -c '
import json, sys
want = sys.argv[1]
for inst in json.load(sys.stdin):
    items = ((inst.get("tags") or {}).get("items")) or []
    if want in items:
        print(inst.get("name") or "")
' "$NETWORK_TAG")"
if [[ -n "$tagged" ]]; then
  echo "Left firewall rules and the thesis- network in place. Other ${NETWORK_TAG} instances remain:"
  printf '%s\n' "$tagged"
  exit 0
fi

"${firewall_cmd[@]}"
if [[ "$keep_network" -eq 1 ]]; then
  echo "Deleted ${VM_NAME} and the thesis- firewall rules. Kept the thesis- network."
  exit 0
fi

on_net="$(gcloud compute instances list --project="$PROJECT" --format=json | python3 -c '
import json, sys
suffix = "/" + sys.argv[1]
for inst in json.load(sys.stdin):
    for nic in inst.get("networkInterfaces") or []:
        net = nic.get("network") or ""
        if net == sys.argv[1] or net.endswith(suffix):
            print(inst.get("name") or "")
            break
' "$THESIS_NETWORK")"
if [[ -n "$on_net" ]]; then
  echo "Left the thesis- network in place. Other instances still use ${THESIS_NETWORK}:"
  printf '%s\n' "$on_net"
  exit 0
fi

if gcloud compute routers nats describe "$THESIS_NAT" \
  --project="$PROJECT" --router="$THESIS_ROUTER" --region="$THESIS_REGION" >/dev/null 2>&1; then
  "${nat_delete_cmd[@]}"
else
  echo "Already absent: nat ${THESIS_NAT}"
fi
if gcloud compute routers describe "$THESIS_ROUTER" \
  --project="$PROJECT" --region="$THESIS_REGION" >/dev/null 2>&1; then
  "${router_delete_cmd[@]}"
else
  echo "Already absent: router ${THESIS_ROUTER}"
fi
if gcloud compute networks subnets describe "$THESIS_SUBNET" \
  --project="$PROJECT" --region="$THESIS_REGION" >/dev/null 2>&1; then
  "${subnet_delete_cmd[@]}"
else
  echo "Already absent: subnet ${THESIS_SUBNET}"
fi
if gcloud compute networks describe "$THESIS_NETWORK" --project="$PROJECT" >/dev/null 2>&1; then
  "${network_delete_cmd[@]}"
else
  echo "Already absent: network ${THESIS_NETWORK}"
fi
echo "Deleted ${VM_NAME}, the thesis- firewall rules, and the thesis- network."
