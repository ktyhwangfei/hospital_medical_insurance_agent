"""
语义层配置文件

定义数据模型1路径、指标定义目录、字典目录等语义层专用配置。
所有路径支持通过环境变量覆盖。
"""
import os
from pathlib import Path

# 项目根目录（src/config/ → 项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 数据模型1 Excel 路径
# raw/数据模型1.xlsx 是语义层的元数据源，包含政策规则表、字典、医保目录三个 Sheet
DATAMODEL1_PATH = os.getenv(
    "DATAMODEL1_PATH",
    str(PROJECT_ROOT / "raw" / "数据模型1.xlsx")
)

# 指标定义 YAML 目录（对标 skills/ 目录）
INDICATORS_DIR = os.getenv(
    "INDICATORS_DIR",
    str(PROJECT_ROOT / "indicators")
)

# 统一字典 YAML 目录
DICTIONARIES_DIR = os.getenv(
    "DICTIONARIES_DIR",
    str(PROJECT_ROOT / "indicators" / "dictionaries")
)

# 自动生成目录（由 datamodel1_importer.py 产出，请勿手工编辑）
AUTO_GENERATED_DIR = os.getenv(
    "AUTO_GENERATED_DIR",
    str(PROJECT_ROOT / "indicators" / "_from_datamodel1")
)
