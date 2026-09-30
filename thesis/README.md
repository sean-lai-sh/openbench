# Thesis run: OpenCode on self-hosted GLM-4.7-Flash

This guide is for the operator who runs OpenCode against `zai-org/GLM-4.7-Flash` on one A100 40GB VM. The scripts create and remove only resources whose names start with `thesis-`. They do not run unless you run them.

## Create the VM

From the repo root, with `gcloud` authenticated to project `nyu-rdg-fy26-js11531-a68d`:

```bash
bash thesis/gcp/create-vllm-vm.sh
```

The script creates `thesis-vllm-glm47` in `us-central1-a` as machine type `a2-highgpu-1g`. The image family is `common-cu128-ubuntu-2204-nvidia-570` from project `deeplearning-platform-release`. If that family is missing, set `IMAGE_FAMILY` to a current CUDA Deep Learning VM family and run the script again.

If `us-central1-a` has no A100 capacity, set `ZONE` to another `us-central1` zone and run the script again. The script rejects zones outside `us-central1`.

The VM has an external address so it can download vLLM and the model weights. Two firewall rules, `thesis-allow-iap-ssh` and `thesis-deny-ingress`, apply only to the `thesis-iap` tag. SSH is allowed from the IAP range `35.235.240.0/20`. Every other ingress source is denied. vLLM binds to `127.0.0.1:8000` inside the guest, so the API is not on the external address.

Startup installs vLLM into `/opt/thesis-vllm` and starts `thesis-vllm.service`. The log is `/var/log/thesis-vllm.log`. The first boot downloads the model, so the API can take a long time to answer.

If Hugging Face requires a token, export `HF_TOKEN` before create. The script passes it as instance metadata. Anyone who can read instances in this project can read that metadata.

Optional knobs, exported in the same shell as the create script:

- `VLLM_MAX_MODEL_LEN` defaults to `16384`.
- `VLLM_EXTRA_ARGS` is extra flags for `vllm serve`, split on spaces.
- `ALLOW_OTHER_MACHINE=1` allows a machine type other than `a2-highgpu-1g`.

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
| `OPENBENCH_GCP_VLLM_MODEL` | yes | Model id the server reports, for example `zai-org/GLM-4.7-Flash` |
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

`--task` takes a comma-separated list. `--exec local` runs the harness on this machine. `--allow-version-drift` is there because `obench legacy run` refuses a host `opencode` whose version differs from `obench/docker/Dockerfile`. Rows then record `version_drift=true`. `--timeout 7200` is the per-task adapter budget in seconds.

Results land in `results/thesis-opencode-glm-4.7-flash.jsonl`. That directory is gitignored.

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

## Assumptions

The default image family is a guess at a current CUDA Deep Learning VM family. Confirm it with `gcloud compute images list` if create fails on the image.

`16384` context on one 40GB A100 may be too large for this checkpoint. Lower `VLLM_MAX_MODEL_LEN`, or pass a quantization flag through `VLLM_EXTRA_ARGS`, if vLLM exits during weight load.

OpenCode edits files through tool calls. This script does not pass a vLLM tool parser. If the agent never edits files, set `VLLM_EXTRA_ARGS` to the parser that matches this checkpoint and create the VM again.

The run script does not pass `--proxy`. Token counts come from OpenCode's JSONL stream, not the counting proxy.
