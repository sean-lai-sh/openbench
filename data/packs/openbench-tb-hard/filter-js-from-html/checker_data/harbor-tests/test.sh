#!/bin/bash

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

_h2_task="$(basename "${TASK_DIR:-}")"
# Private copy of the h2-checker-venvs artifact, set only for the checker process.
_h2_root="${H2_CHECKER_VENV_ROOT:-/opt/h2-checker-venvs}"
_h2_py="${_h2_root}/${_h2_task}/bin/python"
if [ -x "${_h2_py}" ]; then
  "${_h2_py}" -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
else
  if [ -n "${H2_CHECKER_VENV_ROOT:-}" ]; then
    # Split checker venvs are configured: never install, fail closed.
    echo "OBENCH_ENV_FAILURE: checker_venv_missing ${_h2_py} is not executable"
    exit 1
  fi
  # Install curl
  apt-get update
  apt-get install -y curl

  # Install uv
  curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh

  source $HOME/.local/bin/env

  # Check if we're in a valid working directory
uvx \
  -p 3.13 \
  -w pytest==8.4.1 \
  -w selenium==4.38.0 \
  -w bs4==0.0.2 \
  -w pytest-json-ctrf==0.3.5 \
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
fi


if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
