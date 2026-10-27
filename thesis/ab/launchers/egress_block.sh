#!/bin/bash
# Fail-closed egress backstop for step-8 launches (PR #166).
# Blocks outbound VM traffic to api.anthropic.com for the whole run so a
# provider route flip errors instead of reaching the real Anthropic API.
#   host:      iptables/ip6tables OUTPUT REJECT on every resolved IP, tagged
#              with comment $EGRESS_TAG (cells run with --network host, so
#              container traffic goes through the host OUTPUT chain)
#   container: --add-host api.anthropic.com:0.0.0.0 (DNS sinkhole; $EGRESS_ADD_HOST)
# Usage: source this, then egress_apply && egress_verify; trap egress_remove EXIT
# Standalone: bash egress_block.sh apply|verify|remove|status [image]
EGRESS_HOST=${EGRESS_HOST:-api.anthropic.com}
EGRESS_TAG=${EGRESS_TAG:-obench-s8-egress}
EGRESS_ADD_HOST="--add-host $EGRESS_HOST:0.0.0.0"
EGRESS_STATE=${EGRESS_STATE:-/tmp/$EGRESS_TAG.ips}

_egress_ips(){ getent ahosts "$EGRESS_HOST" | awk '{print $1}' | sort -u; }

egress_apply(){
  local ips ip; ips=$(_egress_ips)
  [ -n "$ips" ] || { echo "egress: cannot resolve $EGRESS_HOST" >&2; return 1; }
  echo "$ips" > "$EGRESS_STATE"
  for ip in $ips; do
    if [[ $ip == *:* ]]; then t=ip6tables; r=icmp6-adm-prohibited; else t=iptables; r=icmp-admin-prohibited; fi
    sudo $t -C OUTPUT -d "$ip" -m comment --comment "$EGRESS_TAG" -j REJECT --reject-with $r 2>/dev/null ||
      sudo $t -I OUTPUT 1 -d "$ip" -m comment --comment "$EGRESS_TAG" -j REJECT --reject-with $r || return 1
  done
  echo "egress: blocked $EGRESS_HOST -> $(echo $ips)"
}

# Delete every rule carrying the tag (also catches IPs that rotated since apply).
egress_remove(){
  local t n
  for t in iptables ip6tables; do
    while n=$(sudo $t -L OUTPUT --line-numbers -n 2>/dev/null | awk -v tag="$EGRESS_TAG" '$0 ~ "/\\* "tag" \\*/" {print $1; exit}'); [ -n "$n" ]; do
      sudo $t -D OUTPUT "$n" || break
    done
  done
  rm -f "$EGRESS_STATE"
  echo "egress: removed $EGRESS_TAG rules"
}

egress_status(){ for t in iptables ip6tables; do sudo $t -S OUTPUT | grep -- "$EGRESS_TAG"; done; }

# Must FAIL to reach the host: from the VM, and from a container started the
# way cells are (host network + sinkhole). Returns 0 only when both are blocked.
egress_verify(){
  local img=${1:-${IMG:-}} ok=0 out
  out=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "https://$EGRESS_HOST/v1/models" 2>&1)
  if [ $? -eq 0 ]; then echo "egress: HOST REACHED $EGRESS_HOST (http $out)"; ok=1
  else echo "egress: host blocked ($out)"; fi
  # Direct-IP attempt bypasses DNS: proves the iptables rule, not just DNS.
  local ip; ip=$(head -1 "$EGRESS_STATE" 2>/dev/null)
  if [ -n "$ip" ]; then
    out=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' --resolve "$EGRESS_HOST:443:$ip" "https://$EGRESS_HOST/v1/models" 2>&1)
    if [ $? -eq 0 ]; then echo "egress: IP $ip REACHED (http $out)"; ok=1
    else echo "egress: ip $ip blocked ($out)"; fi
  fi
  if [ -n "$img" ]; then
    out=$(sudo docker run --rm --network host $EGRESS_ADD_HOST "$img" bash -c \
      "getent hosts $EGRESS_HOST; curl -sS -m 10 -o /dev/null -w '%{http_code}' https://$EGRESS_HOST/v1/models" 2>&1)
    if [ $? -eq 0 ]; then echo "egress: CONTAINER REACHED $EGRESS_HOST ($out)"; ok=1
    else echo "egress: container blocked ($(echo $out | tr '\n' ' '))"; fi
  fi
  return $ok
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    apply) egress_apply ;; remove) egress_remove ;; status) egress_status ;;
    verify) egress_verify "${2:-}" ;; *) echo "usage: $0 apply|verify [image]|remove|status"; exit 2 ;;
  esac
fi
