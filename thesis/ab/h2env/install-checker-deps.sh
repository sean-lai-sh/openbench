#!/bin/bash
# Install each H2 checker's Python deps into /opt/h2-checker-venvs/<task>.
# Torch is the CPU wheel from the pinned index, installed before PyPI deps so
# a later requirements line cannot replace it with the default CUDA wheel.
# Checker scripts call this interpreter and skip uvx when it exists.
set -euo pipefail

ROOT="${H2_CHECKER_VENV_ROOT:-/opt/h2-checker-venvs}"
REQ_DIR="${1:-/opt/h2-checker-requirements}"
UV_VERSION="${UV_VERSION:-0.9.5}"

export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

mkdir -p "${ROOT}"

header() {
  # header <file> <key>  — value after "# <key>:"
  awk -v key="$2" '
    $1 == "#" && $2 == key":" {
      $1 = ""; $2 = "";
      sub(/^[[:space:]]+/, "");
      print;
      exit
    }
  ' "$1"
}

for req in "${REQ_DIR}"/*.txt; do
  name="$(basename "${req}" .txt)"
  py="$(header "${req}" python)"
  torch_index="$(header "${req}" torch-index)"
  torch_spec="$(header "${req}" torch)"
  if [ -z "${py}" ]; then
    echo "missing # python: pin in ${req}" >&2
    exit 1
  fi
  uv python install "${py}"
  uv venv --python "${py}" "${ROOT}/${name}"
  pybin="${ROOT}/${name}/bin/python"
  if [ -n "${torch_spec}" ]; then
    if [ -z "${torch_index}" ]; then
      echo "missing # torch-index: for ${name}" >&2
      exit 1
    fi
    # shellcheck disable=SC2086
    uv pip install --python "${pybin}" --index-url "${torch_index}" ${torch_spec}
  fi
  grep -v -E '^[[:space:]]*(#|$)' "${req}" > "/tmp/h2-req-${name}.txt"
  if [ -s "/tmp/h2-req-${name}.txt" ]; then
    uv pip install --python "${pybin}" -r "/tmp/h2-req-${name}.txt"
  fi
  "${pybin}" -c "import pytest"
done

weights="${ROOT}/sam-cell-seg/mobile_sam.pt"
if [ -d "${ROOT}/sam-cell-seg" ] && [ ! -s "${weights}" ]; then
  curl -fsSL -o "${weights}" \
    "https://github.com/ChaoningZhang/MobileSAM/raw/34bbbfdface3c18e5221aa7de6032d7220c6c6a1/weights/mobile_sam.pt" \
    || curl -fsSL -o "${weights}" \
      "https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt"
fi

chmod -R a+rX "${ROOT}"
