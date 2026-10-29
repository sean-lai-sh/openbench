#!/bin/bash

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

_h2_task="$(basename "${TASK_DIR:-}")"
_h2_py="/opt/h2-checker-venvs/${_h2_task}/bin/python"
if [ -x "${_h2_py}" ]; then
  "${_h2_py}" -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
else
  apt-get update
  apt-get install -y curl primer3

  # Install uv
  curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh

  source $HOME/.local/bin/env

  # Check if we're in a valid working directory
uvx \
  -p 3.13 \
  -w pytest==8.4.1 \
  -w pytest-json-ctrf==0.3.5 \
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
fi


if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
