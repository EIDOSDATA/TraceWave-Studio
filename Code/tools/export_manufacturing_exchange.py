"""! @brief 게시된 KiCad 패키지의 제조 교환 후보를 생성한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rfad.adapters.exchange.manufacturing_export import export_package, main


if __name__ == "__main__":
    main()
