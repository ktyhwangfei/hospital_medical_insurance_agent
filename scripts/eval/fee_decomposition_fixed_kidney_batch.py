"""Issue #82 独立定额批测，复用既有逐字段/计算轨迹报告格式。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.fee_decomposition_special_mz_batch import main

if __name__ == "__main__":
    sys.exit(main(kidney_fixed=True))
