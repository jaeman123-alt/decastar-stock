# tools.py

from __future__ import annotations
import math
import os

from typing import Optional
from typing import Any

# 테스트 출력 스위치 (기본 True)
b_Test: bool = True

def set_test_mode(on: bool) -> None:
    """다른 모듈에서 테스트 출력 on/off"""
    global b_Test
    b_Test = on

def tprint(*args: Any, **kwargs: Any) -> None:
    """b_Test가 True일 때만 print"""
    if b_Test:
        print(*args, **kwargs)


# --- Windows CMD에서 ANSI 이스케이프(커서 이동) 활성화 ---
def _enable_ansi_on_windows() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        # 실패해도 치명적이지 않음(단, 커서 이동이 불가할 수 있음)
        pass

"""'+68900' '-68900' 같은 문자열을 절대값 정수로 변환 (표시에 사용). 실패 시 None."""
def _to_abs_int(value):    
    try:
        s = str(value).strip()
        # 숫자만 추출
        digits = "".join(ch for ch in s if ch.isdigit())
        return int(digits) if digits else None
    except Exception:
        return None    
    

def floor_to(n, base=100):
    """엑셀 FLOOR: -∞ 방향 내림"""
    return base * math.floor(n / base)

def ceil_to(n, base=100):
    """엑셀 CEILING: +∞ 방향 올림"""
    return base * math.ceil(n / base)

def trunc_to(n, base=100):
    """엑셀 ROUNDDOWN: 0 방향 절삭"""
    return base * math.trunc(n / base)

def round_to(n, base=100):
    """파이썬 기본 반올림(은행가 반올림: .5는 짝수로)"""
    return int(base * round(n / base))

def xls_round(n, base=100):
    """엑셀 ROUND와 동일(0에서 멀어지는 .5 반올림)"""
    q = Decimal(str(n)) / Decimal(str(base))
    return int((q.quantize(Decimal('0'), rounding=ROUND_HALF_UP)) * base)    

def clear_prev_lines(n: int, stay_at_top: bool = True) -> None:
    import sys
    for _ in range(n):
        sys.stdout.write("\x1b[1A")  # 위로 1줄
        sys.stdout.write("\x1b[2K")  # 그 줄 지우기
    if not stay_at_top:
        sys.stdout.write(f"\x1b[{n}B")  # 지우기 전 위치로 복귀
    sys.stdout.flush()



#import * 를 사용할때 사용하는 ... 공개 명? 같은거 하지만 명시적으로 써서 쓰자
__all__ = ["b_Test", "set_test_mode", "tprint","_enable_ansi_on_windows","_to_abs_int",
           "floor_to","ceil_to","trunc_to","round_to","xls_round","clear_prev_lines"]
