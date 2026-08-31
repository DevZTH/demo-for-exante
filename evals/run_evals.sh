python -m evals.cli list-datasets
python -m evals.cli run --dataset aggressive_sales --runs 3
python -m evals.cli run --dataset all --runs 3
python -m evals.cli compare old.json new.json