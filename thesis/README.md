# Serve GLM-4.7-Flash for the OpenCode thesis run

This guide is for the operator who starts the GPU VM, opens the tunnel, and runs the three hard tasks. The scripts create and remove only resources whose names start with `thesis-`. They do not run unless you run them.

## Create the VM

From the repo root, with `gcloud` authenticated to project `nyu-rdg-fy26-js11531-a68d`:

```bash
bash thesis/gcp/create-vllm-vm.sh
```

The script creates `thesis-vllm-glm47` as machine type `g2-standard-24` and tries `us-central1-a` first. That machine has two NVIDIA L4 GPUs, 48GB of GPU memory in total. The image family is `common-cu129-ubuntu-2204-nvidia-580` from project `deeplearning-platform-release`. Google's Deep Learning VM image page, updated 2026-09-24, lists that family as the CUDA 12.9 GPU base image with driver 580. The previous family, `common-cu128-ubuntu-2204-nvidia-570`, reached end of patch on 2026-04-13.

If you set neither `ZONE` nor `ZONES`, the script tries `us-central1-a`, then `us-central1-b`, then `us-central1-c`. It moves to the next zone only when `gcloud` reports that the zone has no capacity. Any other error stops the script. On the first run, `us-central1-a` and `us-central1-b` had no L4 capacity and `us-central1-c` worked. Set `ZONE=us-central1-c` to pin one zone. Set `ZONES` to a space-separated list when you want a different order. The script rejects zones outside `us-central1`.

This project has no network named `default`. Organization policy `constraints/compute.vmExternalIpAccess` bans external IPs on VMs. Leave `NETWORK` unset. The script creates `thesis-vpc`, subnet `thesis-subnet-usc1` in `us-central1` (`10.10.0.0/20`), `thesis-router`, and `thesis-nat` when they are missing. Cloud NAT is how the VM downloads pip packages and model weights without an external address. The script refuses `NETWORK=default` and refuses the shared network `nyu-rdg-fy26-js11531-net`. Set `NETWORK` and `SUBNET` when you already operate a different VPC. `NO_ADDRESS` defaults to `1`, which passes `--no-address`. Set `NO_ADDRESS=0` only when that VPC is allowed to give the VM an external address. Set `SUBNET_RANGE` to change the `thesis-subnet-usc1` CIDR before the subnet exists.

Firewall rules `thesis-allow-iap-ssh` and `thesis-deny-ingress` are created on the network you chose. They apply only to the `thesis-iap` tag. SSH is allowed from the IAP range `35.235.240.0/20` on `tcp:22`. Every other ingress source is denied. The operator tunnel is an SSH local forward, so port 8000 does not need its own rule. vLLM binds to `127.0.0.1:8000` inside the guest.

The instance metadata sets `block-project-ssh-keys=TRUE`. `gcloud compute ssh` then writes your key onto this VM. It does not write project-wide `ssh-keys` metadata. Do not run `gcloud compute config-ssh` in this shared project. That command adds a key for every VM. OS Login is the other way to keep keys off project metadata. This script does not enable OS Login, because the VM would then require `roles/compute.osLogin`.

Startup installs vLLM `0.30.0` into `/opt/thesis-vllm` and starts `thesis-vllm.service`. The unit sets `PATH` to `/opt/thesis-vllm/bin` and `/usr/local/cuda/bin` ahead of the default directories. Without that, systemd does not find `ninja`. The log is `/var/log/thesis-vllm.log`. The first boot downloads the model, so the API can take a long time to answer. A later boot does not reinstall vLLM when `/opt/thesis-vllm/bin/vllm` already exists. Delete the VM and create it again after you change the install pin.

If Hugging Face requires a token, export `HF_TOKEN` before create. The script passes it as instance metadata. Anyone who can read instances in this project can read that metadata.

On-demand price for `g2-standard-24` in `us-central1` is about $2.00 per hour. CloudPrice lists $2.0008, DevZero lists $2.001, and Holori lists $2.0008 as of 2026-09-07. The 200GB boot disk is extra. These figures come from third-party calculators, not from a billing export of this project.

## Checkpoint and serve flags

The default checkpoint is `unsloth/GLM-4.7-Flash-FP8-Dynamic`. Hugging Face reports that file at 30.29 GiB. The official BF16 checkpoint `zai-org/GLM-4.7-Flash` is 31B parameters and 58.16 GiB of safetensors, which does not fit one 40GB A100. There is no official FP8 of the Flash model. `zai-org/GLM-4.7-FP8` is the 358B model. A100 80GB, machine type `a2-ultragpu-1g`, is not in the stated `us-central1` quota, which lists 16 A100 40GB, 32 L4, 16 T4, and 8 V100. One L4 is 24GB, so the 30.29 GiB file does not fit one L4 either.

`vllm serve` runs with `--tensor-parallel-size 2`, `--max-model-len 32768`, `--dtype bfloat16`, `--enable-auto-tool-choice`, `--tool-call-parser glm47`, and `--reasoning-parser glm45`. vLLM `0.30.0` registers the parser name `glm47`, and its tool-calling doc lists `zai-org/GLM-4.7-Flash` under that parser. The same release registers `glm45` as a reasoning parser. The Hugging Face card for `zai-org/GLM-4.7-Flash` uses those two flags. OpenCode edits files through tool calls, so the server has to parse them.

`--served-model-name` is the checkpoint id. `thesis/run-hard-tasks.sh` sends that same id unless you set `OPENBENCH_GCP_VLLM_MODEL`.

`VLLM_MAX_MODEL_LEN` defaults to 32768. On the first 2x L4 run, OpenCode's system prompt was about 7.2k tokens and turns reached about 14.6k. The KV cache fit about 38.9k tokens, so 32768 stays under that fit. The earlier default of 8192 came from a published run of `marksverdhei/GLM-4.7-Flash-FP8` on two 24GB GPUs, about 14.7GB per GPU, with vLLM 0.13.0. The Unsloth file is a different checkpoint of about the same size. At `--gpu-memory-utilization 0.90` the two L4 GPUs budget about 43GB. If `/var/log/thesis-vllm.log` shows the model does not fit, lower `VLLM_MAX_MODEL_LEN` and create the VM again. Do not add `--kv-cache-dtype fp8`. vLLM issue 38652 reports garbage output on this model when that flag is set.

The model card also passes speculative MTP. This script leaves it off so that memory stays available for the KV cache.

## Change the machine or the parallel size

`MACHINE_TYPE` and `TENSOR_PARALLEL_SIZE` are environment variables. Set them in the same shell as the create script. The script no longer refuses a machine type other than the default. It still refuses a `VM_NAME` that does not start with `thesis-`.

To serve the official BF16 checkpoint on two A100 40GB GPUs instead, export the overrides and run create:

```bash
MACHINE_TYPE=a2-highgpu-2g \
TENSOR_PARALLEL_SIZE=2 \
VLLM_MODEL=zai-org/GLM-4.7-Flash \
VLLM_MAX_MODEL_LEN=8192 \
bash thesis/gcp/create-vllm-vm.sh
```

`a2-highgpu-2g` is about $7.35 per hour in `us-central1`. CloudPrice and Economize both list $7.3468. The two GPUs have 80GB. At `--gpu-memory-utilization 0.90` the budget is about 72GB, and the BF16 files are 58.16 GiB, so about 14GB remains for activations and the KV cache. The official serve example uses tensor parallel size 4. If vLLM exits during weight load, lower `VLLM_MAX_MODEL_LEN`.

Set `OPENBENCH_GCP_VLLM_MODEL` to the same id you passed as `VLLM_MODEL` before you run the tasks.

Other knobs, exported in the same shell:

- `VLLM_DTYPE` defaults to `bfloat16`. Allowed values are `auto`, `bfloat16`, `float16`, and `float32`.
- `VLLM_TOOL_CALL_PARSER` defaults to `glm47`.
- `VLLM_REASONING_PARSER` defaults to `glm45`.
- `VLLM_EXTRA_ARGS` is extra flags for `vllm serve`, split on spaces. Do not repeat the tool parser flags there.
- `IMAGE_FAMILY` overrides the Deep Learning VM family.
- `VLLM_VERSION` overrides the pinned vLLM release. Use a dotted release such as `0.30.0`.

## Open the tunnel

Leave this running in its own terminal. The example uses `us-central1-a`. Replace `--zone` with the zone create printed. `thesis/run-hard-tasks.sh` uses `$ZONE` in its tunnel hint, and that variable defaults to `us-central1-a`.

```bash
gcloud compute ssh thesis-vllm-glm47 \
  --project=nyu-rdg-fy26-js11531-a68d \
  --zone=us-central1-a \
  --tunnel-through-iap \
  -- -N -L 8000:127.0.0.1:8000
```

Your OpenCode process talks to `http://127.0.0.1:8000/v1` on the operator machine. That port is the tunnel, not a public listener.

## Environment variables

The adapter `gcp-vllm/glm-4.7-flash` reads these variables and stores no endpoint of its own.

| Variable | Required | Meaning |
| --- | --- | --- |
| `OPENBENCH_GCP_VLLM_BASE_URL` | yes | OpenAI-compatible base URL, for example `http://127.0.0.1:8000/v1` |
| `OPENBENCH_GCP_VLLM_MODEL` | yes | Model id the server reports, for example `unsloth/GLM-4.7-Flash-FP8-Dynamic` |
| `OPENBENCH_GCP_VLLM_API_KEY` | no | Sent only when vLLM was started with an API key |
| `OPENBENCH_GCP_VLLM_CONTEXT` | no | OpenCode context limit. Default 32768 when unset |
| `OPENBENCH_GCP_VLLM_MAX_OUTPUT` | no | OpenCode output limit. Default 8192 when unset |

`thesis/run-hard-tasks.sh` fills the base URL and model name with those examples when you leave them unset. Set them yourself when the tunnel port or the served name differs.

OpenCode sends `max_tokens=32000` for a model it does not know. vLLM returns HTTP 400 when that request is larger than `--max-model-len` minus the prompt. The adapter always writes a model `limit` for `gcp-vllm/glm-4.7-flash`. Unset variables use 32768 context and 8192 output. Output cannot be larger than context. A prompt of about 14.6k tokens plus an 8192 output cap fits in 32768.

## Run the three hard tasks

Install OpenBench into a virtualenv and activate it before the run.

```bash
uv venv
uv pip install -e .
source .venv/bin/activate
```

`obench` must then be on `PATH`, or `python3 -m obench` must work from that checkout. OpenCode must be on `PATH`. The tunnel must already answer `/v1/models`.

```bash
bash thesis/run-hard-tasks.sh
```

The script runs:

```bash
obench legacy run \
  --exec local \
  --harness opencode \
  --model gcp-vllm/glm-4.7-flash \
  --task make-ci-green,add-feature,misleading-error \
  --results-path results/thesis-opencode-glm-4.7-flash.jsonl \
  --timeout 7200 \
  --allow-version-drift
```

`--task` takes a comma-separated list. `--exec local` runs the harness on this machine. `--exec docker` does not receive `OPENBENCH_GCP_VLLM_BASE_URL` or `OPENBENCH_GCP_VLLM_MODEL`. `--allow-version-drift` is there because `obench legacy run` refuses a host `opencode` whose version differs from `obench/docker/Dockerfile`. Rows then record `version_drift=true`. `--timeout 7200` is the per-task adapter budget in seconds.

Results land in `results/thesis-opencode-glm-4.7-flash.jsonl`. That directory is gitignored. A second run of the same file skips a cell that already has a row for that harness, task, model, and trial. The script appends its extra arguments to `obench legacy run`. Pass `--force` when you change the endpoint or the checkpoint and want those cells again.

```bash
bash thesis/run-hard-tasks.sh --force
```

The run script does not pass `--proxy`. Token counts come from OpenCode's JSONL stream, not the counting proxy.

## Stop and delete

Stop the VM when you want to keep the disk and halt GPU billing:

```bash
bash thesis/gcp/teardown-vllm-vm.sh stop
```

Delete the VM. When no other `thesis-iap` instance remains, the script deletes the two `thesis-` firewall rules. It then deletes `thesis-nat`, `thesis-router`, `thesis-subnet-usc1`, and `thesis-vpc` when no instance still uses that network. The check lists instances and reads tags in the shell. It does not use a `gcloud` tag filter. Pass `--keep-network` to leave the VPC, subnet, router, and NAT in place.

```bash
bash thesis/gcp/teardown-vllm-vm.sh delete
bash thesis/gcp/teardown-vllm-vm.sh --keep-network delete
```

Both commands refuse a `VM_NAME` that does not start with `thesis-`. Set `VM_NAME` and `ZONE` to the values create printed. `ZONE` still defaults to `us-central1-a`. Teardown only deletes names that start with `thesis-`.

## What this guide does not verify

`gcloud` was not run against project `nyu-rdg-fy26-js11531-a68d` for this change. The image family comes from the public Deep Learning VM docs, not from `gcloud compute images list` in that project. Confirm the family if create fails on the image. Cloud NAT address quota was not checked here. If NAT creation fails, the organization may also restrict NAT IPs.

The vLLM `0.30.0` wheel was not installed on this image. If the guest driver rejects the wheel, read `/var/log/thesis-vllm.log`. PyPI lists that release as of 2026-09-22, with a dependency on `transformers>=5.10.4`. The model card's older nightly install is not the default.

The Unsloth checkpoint was not loaded on two L4 GPUs in this change. If weight load OOMs, switch to the `a2-highgpu-2g` BF16 command above, or lower `VLLM_MAX_MODEL_LEN`.
