#!/bin/bash
# Full data build + readiness report on a Slurm cluster (one long job).
#   export DDB_SEC_USER_AGENT="dolla-dolla-bills you@example.com"
#   sbatch --export=ALL hpc/build_all.sbatch            # default steps
#   sbatch --export=ALL,FULL=1 hpc/build_all.sbatch     # plus 13F, minute bars, spreads, congress, contracts, news
# Needs: the repo checked out, a Python env with `pip install -e .`, outbound
# internet from the compute node, and for Alpaca steps a key in ~/.config/ddb/alpaca.env.
# The result is in logs/ and data/db/rl/readiness.md.
#SBATCH --job-name=ddb-build
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --output=logs/build_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
mkdir -p logs
ARGS=()
[ -f data/raw/sec/companyfacts.zip ] || ARGS+=(--download)
[ "${FULL:-0}" = "1" ] && ARGS+=(--full)
python -u scripts/build_all.py "${ARGS[@]}"
