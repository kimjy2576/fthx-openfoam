"""OpenFOAM 경로 패키지 — core(submodule) 를 import 경로에 자동 추가."""
import sys as _sys
from pathlib import Path as _P
_CORE = _P(__file__).resolve().parents[1] / "core"
if str(_CORE) not in _sys.path:
    _sys.path.insert(0, str(_CORE))
