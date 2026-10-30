"""让 pytest 在仓库根目录直接运行时也能导入 rca 包。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
