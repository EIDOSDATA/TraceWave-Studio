"""! @brief TraceWave Studio의 가벼운 서비스 패키지를 정의한다."""

__version__ = "0.1.0.dev0"

import sys as _sys
from rfad._source_loading import install as _install_source_loading

_install_source_loading(_sys._getframe().f_code)
del _install_source_loading, _sys
