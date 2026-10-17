cd /workspace/openbench-ab
export GOOGLE_CLOUD_PROJECT=nyu-rdg-fy26-js11531-a68d VERTEX_LOCATION=global GOOGLE_APPLICATION_CREDENTIALS=/home/box/.config/gcloud/application_default_credentials.json PATH=/home/box/google-cloud-sdk/bin:$PATH
R=/workspace/openbench-ab/results/step3-sonnet-1016
# Step 3: original 34 OpenCode PRs, A/B 30/side, Sonnet 5.5, trigger-tasks.csv tasks. Runner 9439542 (#37 hang class).
# --order interleave (alternate parent/merge inside each trial). Restarted 20:20 after aborting a sides-order start ($5.44, quarantined in step3-sonnet-1016-sidesorder-aborted). Sequential batches, one invocation at a time, shared --out so --order interleave --max-cost-usd 1494 is cumulative.
B1=623,913,984,1248,2334,2367,3052,3115
B2=3369,4204,4838,5066,5131,5140,6524,11731
B3=12214,13090,13198,13269,13331,17053,17098,19058
B4=21070,22390,23771,24974,25226,25431,26821
for b in B1 B2 B3 B4; do
  echo "$(date '+%F %T') start $b ${!b}" >> $R/driver.log
  uv run python -m thesis.ab.run_ab thesis/ab/fixtures/opencode-harness-prs.csv --pr ${!b} --task-map thesis/ab/fixtures/trigger-tasks.csv --trials 30 --jobs 4 --vertex-model claude-sonnet-5-5 --out $R --cache /workspace/openbench-ab/results/opencode-src --order interleave --max-cost-usd 1494 > $R/$b.log 2>&1
  echo "$(date '+%F %T') end $b rc=$?" >> $R/driver.log
done
echo "$(date '+%F %T') all done" >> $R/driver.log
