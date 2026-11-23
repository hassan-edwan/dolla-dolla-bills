#!/bin/bash
# GDELT news backfill on a Slurm cluster: one array task per month, Feb 2015 -> now.
#   sbatch --array=0-141%8 hpc/gdelt_backfill.sbatch
# (%8 = at most 8 months at once, to stay polite to GDELT's servers.)
# Needs: the repo checked out, a Python env with `pip install -e .`, and
# data/reference/gdelt_aliases.csv (committed). Output: data/db/news_events/*.parquet
# Copy those files back to the main machine afterwards (they are not in git).
#SBATCH --job-name=gdelt-backfill
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=12:00:00
#SBATCH --output=logs/gdelt_%A_%a.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
mkdir -p logs
START=$(python -c "import pandas as pd; m=pd.Period('2015-02','M')+${SLURM_ARRAY_TASK_ID}; print(max(m.start_time, pd.Timestamp('2015-02-18')).date())")
END=$(python -c "import pandas as pd; m=pd.Period('2015-02','M')+${SLURM_ARRAY_TASK_ID}; print(min(m.end_time.normalize(), pd.Timestamp.now().normalize()-pd.Timedelta(days=1)).date())")
echo "month task ${SLURM_ARRAY_TASK_ID}: ${START} .. ${END}"
python -u -m ddb.news.gdelt --start "${START}" --end "${END}" --workers 4
