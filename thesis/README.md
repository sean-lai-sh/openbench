# Serve GLM-4.7-Flash for the OpenCode thesis run

This guide is for the operator who starts the GPU VM, opens the tunnel, and runs the three hard tasks. The scripts create and remove only resources whose names start with `thesis-`. They do not run unless you run them.

## Create the VM

From the repo root, with `gcloud` authenticated to project `nyu-rdg-fy26-js11531-a68d`:

```bash
bash thesis/gcp/create-vllm-vm.sh
```

The script creates `thesis-vllm-glm47` in `us-central1-a` as machine type `g2-standard-24`. That machine has two NVIDIA L4 GPUs, 48GB of GPU memory in total. The image family is `common-cu129-ubuntu-2204-nvidia-580` from project `deeplearning-platform-release`. Google's Deep Learning VM image page, updated 2026-09-24, lists that family as the CUDA 12.9 GPU base image with driver 580. The previous family, `common-cu128-ubuntu-2204-nvidia-570`, reached end of patch on 2026-04-13.

If `us-central1-a` has no L4 capacity, set `ZONE` to another `us-central1` zone and run the script again. The script rejects zones outside `us-central1`.

The VM has an external address so it can download vLLM and the model weights. Two firewall rules, `thesis-allow-iap-ssh` and `thesis-deny-ingress`, apply only to the `thesis-iap` tag. SSH is allowed from the IAP range `35.235.240.0/20`. Every other ingress source is denied. vLLM binds to `127.0.0.1:8000` inside the guest, so the API is not on the external address.

Startup installs vLLM `0.30.0` into `/opt/thesis-vllm` and starts `thesis-vllm.service`. The log is `/var/log/thesis-vllm.log`. The first boot downloads the model, so the API can take a long time to answer. A later boot does not reinstall vLLM when `/opt/thesis-vllm/bin/vllm` already exists. Delete the VM and create it again after you change the install pin.

If Hugging Face requires a token, export `HF_TOKEN` before create. The script passes it as instance metadata. Anyone who can read instances in this project can read that metadata.

On-demand price for `g2-standard-24` in `us-central1` is about $2.00 per hour. CloudPrice lists $2.0008, DevZero lists $2.001, and Holori lists $2.0008 as of 2026-09-07. The 200GB boot disk is extra. These figures come from third-party calculators, not from a billing export of this project.

## Checkpoint and serve flags

The default checkpoint is `unsloth/GLM-4.7-Flash-FP8-Dynamic`. Hugging Face reports that file at 30.29 GiB. The official BF16 checkpoint `zai-org/GLM-4.7-Flash` is 31B parameters and 58.16 GiB of safetensors, which does not fit one 40GB A100. There is no official FP8 of the Flash model. `zai-org/GLM-4.7-FP8` is the 358B model. A100 80GB, machine type `a2-ultragpu-1g`, is not in the stated `us-central1` quota, which lists 16 A100 40GB, 32 L4, 16 T4, and 8 V100. One L4 is 24GB, so the 30.29 GiB file does not fit one L4 either.

`vllm serve` runs with `--tensor-parallel-size 2`, `--max-model-len 8192`, `--dtype bfloat16`, `--enable-auto-tool-choice`, `--tool-call-parser glm47`, and `--reasoning-parser glm45`. vLLM `0.30.0` registers the parser name `glm47`, and its tool-calling doc lists `zai-org/GLM-4.7-Flash` under that parser. The same release registers `glm45` as a reasoning parser. The Hugging Face card for `zai-org/GLM-4.7-Flash` uses those two flags. OpenCode edits files through tool calls, so the server has to parse them.

`--served-model-name` is the checkpoint id. `thesis/run-hard-tasks.sh` sends that same id unless you set `OPENBENCH_GCP_VLLM_MODEL`.

8192 is the default context because `marksverdhei/GLM-4.7-Flash-FP8` published a run on two 24GB GPUs at that length, about 14.7GB per GPU, with vLLM 0.13.0. The Unsloth file is a different checkpoint of about the same size. This change did not boot the VM, so the fit on `g2-standard-24` is inferred from that VRAM class. At `--gpu-memory-utilization 0.90` the two L4 GPUs budget about 43GB. The 30.29 GiB file leaves about 13GB for activations and the KV cache. A longer context spends that remainder. If `/var/log/thesis-vllm.log` shows free GPU memory after load, raise `VLLM_MAX_MODEL_LEN` and create the VM again. Do not add `--kv-cache-dtype fp8`. vLLM issue 38652 reports garbage output on this model when that flag is set.

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

Leave this running in its own terminal. Replace the zone if you did not use `us-central1-a`.

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

`thesis/run-hard-tasks.sh` fills the base URL and model name with those examples when you leave them unset. Set them yourself when the tunnel port or the served name differs.

## Run the three hard tasks

`obench` must be on `PATH`, or `python3 -m obench` must work from a checkout where the package is installed. OpenCode must be on `PATH`. The tunnel must already answer `/v1/models`.

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

Results land in `results/thesis-opencode-glm-4.7-flash.jsonl`. That directory is gitignored. A second run of the same file skips a cell that already has a row for that harness, task, model, and trial. Pass `--force` to `obench legacy run` when you change the endpoint or the checkpoint and want those cells again. The run script does not forward extra arguments, so add `--force` by editing the script or by calling `obench` yourself.

The run script does not pass `--proxy`. Token counts come from OpenCode's JSONL stream, not the counting proxy.

## Stop and delete

Stop the VM when you want to keep the disk and halt GPU billing:

```bash
bash thesis/gcp/teardown-vllm-vm.sh stop
```

Delete the VM, and delete the two `thesis-` firewall rules when no other `thesis-iap` instance remains:

```bash
bash thesis/gcp/teardown-vllm-vm.sh delete
```

Both commands refuse a `VM_NAME` that does not start with `thesis-`. Set `VM_NAME` and `ZONE` to the same values you used at create time.

## What this guide does not verify

`gcloud` was not run against project `nyu-rdg-fy26-js11531-a68d`. The image family comes from the public Deep Learning VM docs, not from `gcloud compute images list` in that project. Confirm the family if create fails on the image.

The vLLM `0.30.0` wheel was not installed on this image. If the guest driver rejects the wheel, read `/var/log/thesis-vllm.log`. PyPI lists that release as of 2026-09-22, with a dependency on `transformers>=5.10.4`. The model card's older nightly install is not the default.

The Unsloth checkpoint was not loaded on two L4 GPUs in this change. If weight load OOMs, switch to the `a2-highgpu-2g` BF16 command above, or lower `VLLM_MAX_MODEL_LEN`.
