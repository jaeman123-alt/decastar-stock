# ===============================
# file: SHApp_kodex_leverage_oto_state_machine.py
# version : 2.3.0
# ===============================
# python SHApp_kodex_leverage_oto.py
#
# 기능 요약
# v2.2.0
#    - 최초 계좌금액의 50%만 진입하고, 나머지 50%는 10단계 물타기 예산으로 보관합니다.
#    - DCA트리거선 터치 시 즉시 매도하지 않고 단계별 추가매수(DCA)를 실행합니다.
#    - 추가매수 후 평균단가 기준으로 익절 지정가를 다시 등록합니다.
#    - DCA 단계가 모두 소진된 뒤 DCA트리거선에 다시 닿으면 최종 DCA트리거합니다.
#    - 거래/전략 이벤트 CSV 저장 및 종료 리포트를 유지합니다.
# 1) 일반 모드
#    - 계좌 정보, 현재가, 예상 매수수량/금액 표시
#    - 사용자 승인 후 KODEX SK하이닉스/삼성전자 단일종목레버리지 50:50 지정가/시장가 매수
#    - 체결 대기 중 진행상황 출력
#    - 체결가 기준 종목별 익절 %로 지정가 매도 등록
#    - 종목별 DCA트리거 % 가격을 계산하고, DCA 감시가 켜져 있으면 현재가 감시 후 해당 종목만 시장가 매도
#    - 익절 체결로 보유수량이 0주가 되면 같은 종목을 시장가로 재매수하고 익절/DCA 감시에 재등록
#    - 지정한 마감 시간이 되면 미체결 주문 취소 후 전체 청산, 계좌 정보 출력, 프로그램 종료
#
# 2) 재시작/복구 모드
#    - 프로그램 강제 종료 후 다시 시작할 때 매수는 PASS
#    - 종목별 매입가만 입력하면 종목별 익절 % / DCA트리거 %로 가격 자동 계산
#    - 계좌 보유/매도가능수량 확인
#    - 익절 지정가 재등록
#    - DCA 감시 진입
#
# 재시작 방법 1: 코드 상단 설정 사용
# RESTORE_MODE = True
# RESTORE_STOCKS = [
#     {"code": "0193T0", "buy_price": 10000},
#     {"code": "0193W0", "buy_price": 10000},
# ]
#
# 재시작 방법 2: 실행 파라미터 사용
# python SHApp_kodex_leverage_oto.py --restore 0193T0:10000 0193W0:10000
# python SHApp_kodex_leverage_oto.py --restore 0193T0:10000 0193W0:10000 --yes
#
# 전체 보유종목 시장가 매도 초기화:
# - 먼저 미체결 주문을 전체/보유종목별로 조회해 취소한 뒤 매도가능수량을 다시 확인하고 시장가 매도합니다.
# python SHApp_kodex_leverage_oto.py --sell-all
# python SHApp_kodex_leverage_oto.py --sell-all --yes
#
# 화면 출력과 파일 저장 동시 실행:
# python SHApp_kodex_leverage_oto.py --yes --log 260626.txt
#
# 주의
# place_loss_cut_sell()은 DCA트리거 예약 함수가 아니라 즉시 시장가 청산 계열 함수입니다.
# 이 파일은 DCA 감시 중 DCA트리거가에 도달한 특정 종목만 매도가능수량 확인 후 시장가 매도합니다.

from __future__ import annotations

import os
import math
import time
import sys
import argparse
import csv
from datetime import datetime, timedelta
from typing import Any

from auth import KiwoomAuth
from kiwoom_client import KiwoomClient
from tools import *


class TeeLogger:
    """콘솔 출력은 그대로 보여주고, 같은 내용을 UTF-8-SIG 로그 파일에도 기록합니다."""

    def __init__(self, console, file_obj):
        self.console = console
        self.file_obj = file_obj
        self.closed = False

    def write(self, message: str) -> int:
        if not isinstance(message, str):
            message = str(message)

        # 화면 출력은 기존 콘솔 인코딩을 그대로 사용합니다.
        try:
            self.console.write(message)
            self.console.flush()
        except Exception:
            pass

        # 파일은 UTF-8-SIG로만 저장합니다. 파일이 닫힌 뒤 flush 예외가 나지 않도록 방어합니다.
        if not self.closed and self.file_obj and not self.file_obj.closed:
            try:
                self.file_obj.write(message)
                self.file_obj.flush()
            except Exception:
                pass

        return len(message)

    def flush(self) -> None:
        try:
            self.console.flush()
        except Exception:
            pass
        if not self.closed and self.file_obj and not self.file_obj.closed:
            try:
                self.file_obj.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return getattr(self.console, "encoding", None) or "utf-8"


_log_tee_state: dict[str, Any] = {
    "stdout": None,
    "stderr": None,
    "file": None,
}


def _setup_log_tee(log_path: str | None):
    if not log_path:
        return None

    # Windows 메모장/엑셀에서 한글이 깨지지 않도록 BOM이 있는 UTF-8로 저장합니다.
    log_file = open(log_path, "a", encoding="utf-8-sig", buffering=1, errors="replace")

    _log_tee_state["stdout"] = sys.stdout
    _log_tee_state["stderr"] = sys.stderr
    _log_tee_state["file"] = log_file

    sys.stdout = TeeLogger(sys.stdout, log_file)
    sys.stderr = TeeLogger(sys.stderr, log_file)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 로그 파일 저장 시작: {log_path}")
    return log_file


def _close_log_tee() -> None:
    log_file = _log_tee_state.get("file")

    # 먼저 stdout/stderr를 원래 객체로 돌려놓고 파일을 닫아야
    # 프로그램 종료 시 'Exception ignored on flushing sys.stdout'가 발생하지 않습니다.
    if _log_tee_state.get("stdout") is not None:
        sys.stdout = _log_tee_state["stdout"]
    if _log_tee_state.get("stderr") is not None:
        sys.stderr = _log_tee_state["stderr"]

    if log_file and not log_file.closed:
        try:
            log_file.flush()
            log_file.close()
        except Exception:
            pass

    _log_tee_state["stdout"] = None
    _log_tee_state["stderr"] = None
    _log_tee_state["file"] = None


# ===============================
# 기본 실행 설정
# ===============================

# 00:00이면 즉시 시작, 예: "09:00"이면 해당 시간까지 대기
start_time: str = "00:00"

# 모의투자 여부. 실전은 False로 변경하세요.
is_paper: bool = True

# ===============================
# 키움 API 접속 설정
# 빈 문자열이면 기존처럼 환경변수에서 읽습니다.
# 보안상 Git 저장소에 올리는 파일에는 값을 비워두는 것을 권장합니다.
# ===============================
KIWOOM_URL: str = "https://mockapi.kiwoom.com"
KIWOOM_APP_KEY: str = "deNdUdk4RvyjwomX7RJtZRZ_6sIMQQvUlBHsvOk0C_w"
KIWOOM_APP_SECRET: str = "T3KJAE_hhuHzfcJLqGvodUz4m3uqYTKQRECi1xgksGM"

# 체결 확인 설정
float_poll: float = 1.0
float_timeout: float = 30.0

# 호가 단위
PRICE_UNIT: int = 50

# 디버그 출력 여부
b_Tprint: bool = False
b_Test: bool = False

# ===============================
# 종목별 매매 설정
# 익절/DCA트리거 %를 종목별로 분리했습니다.
# ===============================

TARGET_STOCKS: list[dict[str, Any]] = [
    {
        "code": "0193T0",
        "name": "KODEX SK하이닉스단일종목레버리지",
        "weight": 0.50,
        "take_profit_pct": 4.0,
        "stop_loss_pct": 3.0,
        "take_profit_schedule": [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        "stop_loss_schedule": [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5],
        "test_down_rate": 0.015,   # TEST_MODE: 1초마다 -1.5%
        "test_sellable_qty": 10,   # TEST_MODE: 가상 매도가능수량
    },
    {
        "code": "0193W0",
        "name": "KODEX 삼성전자단일종목레버리지",
        "weight": 0.50,
        "take_profit_pct": 4.0,
        "stop_loss_pct": 3.0,
        "take_profit_schedule": [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        "stop_loss_schedule": [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5],
        "test_down_rate": 0.010,   # TEST_MODE: 1초마다 -1.0%
        "test_sellable_qty": 10,   # TEST_MODE: 가상 매도가능수량
    },
]

# ===============================
# 재시작/복구 모드 설정
# ===============================

# True이면 신규 매수는 하지 않고 RESTORE_STOCKS의 매입가 기준으로 익절/DCA트리거가를 계산합니다.
RESTORE_MODE: bool = False

# 형식: code + buy_price만 입력합니다.
# 익절가/DCA트리거가는 TARGET_STOCKS의 take_profit_pct, stop_loss_pct로 자동 계산합니다.
RESTORE_STOCKS: list[dict[str, Any]] = [
    # {"code": "0193T0", "buy_price": 10000},
    # {"code": "0193W0", "buy_price": 10000},
]

# RESTORE_MODE=True일 때 확인 질문 없이 바로 실행할지 여부
RESTORE_AUTO_YES: bool = False

# ===============================
# DCA 감시 설정
# ===============================

STOP_LOSS_WATCH_ENABLED: bool = True
STOP_LOSS_CHECK_SEC: float = 1.0
STOP_LOSS_PRINT_SEC: float = 60.0

# ===============================
# DCA 물타기 전략 설정
# ===============================
# 전체 계좌 주문가능금액 중 최초 진입에 사용할 비율입니다.
# 0.50이면 최초에는 전체 자금의 50%만 매수하고, 나머지 50%는 물타기 예산으로 보관합니다.
INITIAL_ENTRY_CASH_RATE: float = 0.50

# 남겨둔 자금 중 DCA 물타기에 사용할 비율입니다.
DCA_RESERVE_CASH_RATE: float = 0.50

# DCA트리거선 터치 시 매도하지 않고 DCA 추가매수를 실행할지 여부입니다.
DCA_ON_STOP_TOUCH_ENABLED: bool = True

# DCA 단계별 예산 가중치입니다. 합계 기준으로 남은 50% 예산을 나눕니다.
# 후반으로 갈수록 더 큰 금액을 투입해 평균단가 인하 효과를 키우는 구조입니다.
DCA_BUDGET_WEIGHTS: list[float] = [1, 1, 2, 2, 3, 4, 5, 6, 8, 10]

# +4 / -3 실험 설정
# 여기서 -3은 실제 손절 매도폭이 아니라 DCA 추가매수 트리거입니다.
# 가격이 기준가 대비 -3% 도달하면 익절 주문을 취소하고 DCA 추가매수 후 평균단가 기준으로 익절을 다시 등록합니다.
DEFAULT_TAKE_PROFIT_PCT: float = 4.0
DEFAULT_DCA_TRIGGER_PCT: float = 3.0

# DCA 후 새 익절가는 평균단가 기준으로 계산합니다.
DCA_TAKE_PROFIT_FROM_AVG_PRICE: bool = True

# DCA 추가매수도 BUY_ORDER_TYPE 설정을 따릅니다.
DCA_BUY_USES_BUY_ORDER_TYPE: bool = True


# 익절 체결 후 자동 재진입 설정
# 익절 지정가 매도가 체결되어 보유수량이 0주가 되면, 같은 종목을 시장가로 다시 매수하고
# 새 체결가 기준으로 익절 주문과 DCA 감시를 다시 설정합니다.
TAKE_PROFIT_REBUY_ENABLED: bool = True

# 재진입 매수는 사용자 요청에 따라 BUY_ORDER_TYPE과 무관하게 시장가로 실행합니다.
# 직전 감시수량을 기준으로 재매수하되, 주문가능금액 부족 시 기존 시장가 재시도 로직이 수량을 줄입니다.
TAKE_PROFIT_REBUY_SAME_QTY: bool = True

# ===============================
# 상태 머신 전략 설정
# ===============================
# NORMAL   : 최초 매수 후 기본 익절/DCA 감시
# RECOVERY : DCA트리거선에 닿았지만 매도하지 않고, 현재가를 새 기준가로 삼아 익절/DCA트리거 가격을 재설정
# EXIT     : 최대 재설정/재진입 횟수 도달 또는 마감 청산

# True이면 DCA트리거가에 도달해도 즉시 매도하지 않고, 현재가 기준으로 익절/DCA트리거 가격을 다시 설정합니다.
# 단, MAX_REBUY_PER_STOCK 횟수에 도달하면 실제 시장가 손절 매도를 실행합니다.
STOP_LOSS_PRICE_RESET_ENABLED: bool = True

# 구버전 호환용 이름입니다. 새 코드에서는 STOP_LOSS_PRICE_RESET_ENABLED를 사용합니다.
STOP_LOSS_REBUY_ENABLED: bool = STOP_LOSS_PRICE_RESET_ENABLED

# 종목별 최대 재진입/DCA트리거가 재설정 횟수입니다.
# 익절 후 재매수와 DCA트리거가 재설정을 합산해서 관리합니다.
MAX_REBUY_PER_STOCK: int = 10

# DCA트리거 재설정 회차별 익절률입니다.
# 예: 0회차는 기본 익절률, DCA트리거 재설정이 누적될수록 목표 익절률을 낮춰 반등 탈출 가능성을 높입니다.
# 종목별 take_profit_schedule이 있으면 그 값을 우선 사용합니다.
DEFAULT_TAKE_PROFIT_SCHEDULE: list[float] = [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0]

# 단타 수수료 부담을 줄이기 위해 익절률은 고정하고, DCA트리거선 터치 때 DCA트리거폭만 점진적으로 확대합니다.
KEEP_TAKE_PROFIT_FIXED_ON_STOP_RESET: bool = True
DEFAULT_STOP_LOSS_SCHEDULE: list[float] = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]

# 거래 기록/리포트 설정
TRADE_CSV_ENABLED: bool = True
TRADE_CSV_PATH: str = ""  # 비우면 trade_history_YYYYMMDD.csv 로 저장
TRADE_REPORT_ENABLED: bool = True
TRADE_EVENTS: list[dict[str, Any]] = []

# DCA트리거 재설정 시 기존 익절 주문을 취소하고 새 기준가 기준 익절 주문을 다시 등록합니다.
RESET_TAKE_PROFIT_ON_STOP_RESET: bool = True

STATE_NORMAL: str = "NORMAL"
STATE_RECOVERY: str = "RECOVERY"
STATE_EXIT: str = "EXIT"

# 매도 후 재매수 전 계좌/잔고 반영 대기시간입니다.
REBUY_WAIT_SEC: float = 3.0

# 마감 청산 설정
# True이면 FORCE_EXIT_TIME에 도달하는 순간 미체결 주문을 취소하고 모든 보유종목을 시장가 청산한 뒤 종료합니다.
FORCE_EXIT_ENABLED: bool = True
FORCE_EXIT_TIME: str = "15:20"

# API 과호출 방지: 잔고조회(kt00018)는 최소 간격을 둡니다.
BALANCE_QUERY_MIN_INTERVAL_SEC: float = 3.0

# 미체결 주문 취소 후 계좌/매도가능수량 반영 대기
ORDER_CANCEL_WAIT_SEC: float = 2.0

# 주문/취소 API 연속 호출 제한 방지용입니다.
# 복구 모드에서 여러 종목의 익절 주문을 연속 등록할 때 HTTP 429가 발생할 수 있어
# 주문 API 호출 사이에 최소 대기시간을 둡니다.
ORDER_API_MIN_INTERVAL_SEC: float = 1.2
ORDER_API_429_RETRY_COUNT: int = 5
ORDER_API_429_RETRY_SLEEP_SEC: float = 2.0


# ===============================
# 매수 주문 방식 설정
# ===============================
# "MARKET" : 시장가 매수. 체결 가능성은 높지만 모의투자/실전에서 증거금을 크게 잡을 수 있습니다.
# "LIMIT"  : 지정가 매수. 주문가격 기준으로 증거금이 계산되어 주문가능금액을 더 근접하게 사용할 수 있습니다.
BUY_ORDER_TYPE: str = "LIMIT"

# 지정가 매수 가격 산정 방식입니다.
# 0.0이면 현재가 기준 지정가, 0.3이면 현재가보다 0.3% 높은 가격으로 지정가 매수합니다.
# 지정가 매수는 주문가격보다 낮거나 같은 가격에서 체결될 수 있습니다.
LIMIT_BUY_UP_PCT: float = 0.3

# 지정가 매수 주문번호를 못 받는 경우 재시도합니다.
LIMIT_BUY_RETRY_COUNT: int = 3
LIMIT_BUY_RETRY_SLEEP_SEC: float = 1.0

# 시장가 매수 시 현재가보다 높은 증거금을 요구할 수 있으므로 주문가능금액의 일부를 여유로 남깁니다.
# 첫 번째 종목은 배정금액이 이 한도보다 작으면 50% 배정금액을 그대로 사용하고,
# 두 번째 이후 종목은 남은 주문가능금액 기준으로 보수적으로 재계산됩니다.
# 예: 남은 주문가능금액 4,600,000원, 비율 0.75 -> 약 3,450,000원까지만 시장가 매수 시도
MARKET_BUY_CASH_SAFETY_RATE: float = 0.75

# 시장가 매수 주문번호를 못 받는 경우 재시도합니다.
MARKET_BUY_RETRY_COUNT: int = 5
MARKET_BUY_RETRY_SLEEP_SEC: float = 2.0

# 시장가 매수 주문번호가 비정상으로 반환될 때 수량을 단계적으로 줄여 재시도합니다.
# 0.95는 5%씩 감량합니다. 0.8처럼 크게 줄이면 두 번째 종목 매수금액이 과도하게 줄어듭니다.
MARKET_BUY_INVALID_REDUCE_RATE: float = 0.95
MARKET_BUY_INVALID_REDUCE_MIN_QTY: int = 1

# True이면 API 현재가 대신 종목별 가상 현재가를 사용합니다.
# 실제 운용 전에는 반드시 False로 바꾸세요.
# ===============================
# TEST MODE
# ===============================

# False : 실제 운용/장중 API 직접 사용
# True  : 장시간 외 디버깅용. 실제 매수/매도 주문은 넣지 않고,
#         체결/가격하락/매도가능수량/주문결과를 모두 가상 처리합니다.
TEST_MODE: bool = False

# TEST_MODE=True일 때 체결 대기 로그를 보여준 뒤, 이 시간이 지나면 현재가로 가상 체결 처리합니다.
TEST_FILL_AFTER_SEC: float = 10.0

# 잔고조회 캐시. kt00018 429 방지용입니다.
_LAST_BALANCE_MAP: dict[str, dict[str, Any]] = {}
_LAST_BALANCE_TS: float = 0.0
_LAST_ORDER_API_TS: float = 0.0


# ===============================
# 공통 유틸
# ===============================


def _trade_csv_path() -> str:
    if TRADE_CSV_PATH:
        return TRADE_CSV_PATH
    return f"trade_history_{datetime.now():%Y%m%d}.csv"


def _log_trade_event(
    event: str,
    stk_cd: str,
    stk_nm: str = "",
    qty: int = 0,
    price: int = 0,
    base_price: int = 0,
    order_no: Any = "",
    profit_amount: int | None = None,
    profit_pct: float | None = None,
    memo: str = "",
    **extra: Any,
) -> None:
    """매매/전략 이벤트를 메모리와 CSV에 기록합니다.

    실제 체결 손익은 증권사 체결/잔고 기준과 다를 수 있으므로, 여기의 profit은 프로그램 기준가 기반 추정값입니다.
    """
    code = _norm_code(stk_cd)
    if not stk_nm:
        stk_nm = _target_name(code)
    row = {
        "time": _now(),
        "event": event,
        "stk_cd": code,
        "stk_nm": stk_nm,
        "qty": int(qty or 0),
        "price": int(price or 0),
        "base_price": int(base_price or 0),
        "order_no": str(order_no or ""),
        "profit_amount": "" if profit_amount is None else int(profit_amount),
        "profit_pct": "" if profit_pct is None else round(float(profit_pct), 4),
        "memo": memo,
    }
    for key, value in extra.items():
        row[key] = value
    TRADE_EVENTS.append(row)

    if not TRADE_CSV_ENABLED:
        return

    path = _trade_csv_path()
    fieldnames = [
        "time", "event", "stk_cd", "stk_nm", "qty", "price", "base_price", "order_no",
        "profit_amount", "profit_pct", "memo", "state", "cycle", "take_profit_price", "stop_loss_price",
    ]
    for key in row.keys():
        if key not in fieldnames:
            fieldnames.append(key)

    file_exists = os.path.exists(path) and os.path.getsize(path) > 0
    try:
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as exc:
        print(f"[{_now()}] 거래 CSV 기록 실패: {exc}")


def _print_trade_report() -> None:
    if not TRADE_REPORT_ENABLED:
        return

    print("\n" + "=" * 72)
    print(f"[{_now()}] 당일 프로그램 거래 리포트")
    print("=" * 72)

    if not TRADE_EVENTS:
        print("기록된 거래/전략 이벤트가 없습니다.")
        return

    by_code: dict[str, dict[str, Any]] = {}
    total_profit = 0
    total_profit_known = False
    for row in TRADE_EVENTS:
        code = str(row.get("stk_cd", ""))
        if code not in by_code:
            by_code[code] = {
                "name": row.get("stk_nm", code),
                "BUY": 0,
                "TAKE_PROFIT_FILLED": 0,
                "REBUY": 0,
                "STOP_RESET": 0,
                "FINAL_STOP_SELL": 0,
                "SELL_ALL": 0,
                "profit": 0,
                "profit_known": False,
            }
        info = by_code[code]
        ev = str(row.get("event", ""))
        if ev in info:
            info[ev] += 1
        pa = row.get("profit_amount", "")
        if pa not in (None, ""):
            try:
                info["profit"] += int(pa)
                info["profit_known"] = True
                total_profit += int(pa)
                total_profit_known = True
            except Exception:
                pass

    for code, info in by_code.items():
        profit_text = f" / 추정손익 {format(info['profit'], ',')}원" if info["profit_known"] else ""
        print(
            f"- {info['name']}[{code}] "
            f"매수 {info['BUY']}회 / 재매수 {info['REBUY']}회 / 익절추정 {info['TAKE_PROFIT_FILLED']}회 / "
            f"DCA트리거재설정 {info['STOP_RESET']}회 / 최종손절 {info['FINAL_STOP_SELL']}회 / 전체청산 {info['SELL_ALL']}회"
            f"{profit_text}"
        )

    if total_profit_known:
        print(f"총 추정 손익: {format(total_profit, ',')}원")
    print(f"CSV 저장 위치: {_trade_csv_path() if TRADE_CSV_ENABLED else '비활성화'}")


def wait_until(hhmm: str) -> None:
    if hhmm == "00:00":
        return

    _enable_ansi_on_windows()

    try:
        hh, mm = map(int, hhmm.split(":"))
    except Exception:
        raise SystemExit("start_time은 HH:MM 형식이어야 합니다. 예: 09:00")

    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    print(f"예약시간 {target:%Y-%m-%d %H:%M:%S}")
    print(f"현재시각 {datetime.now():%Y-%m-%d %H:%M:%S}")

    try:
        while True:
            now = datetime.now()
            if now >= target:
                sys.stdout.write("\033[1A\033[2K")
                sys.stdout.write(f"현재시각 {now:%Y-%m-%d %H:%M:%S}\n")
                sys.stdout.flush()
                print("시간 도달! 작업을 시작합니다.")
                break

            sys.stdout.write("\033[1A\033[2K")
            sys.stdout.write(f"현재시각 {now:%Y-%m-%d %H:%M:%S}\n")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        print("사용자 중단(Ctrl+C)")
        sys.exit(1)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def _norm_code(stk_cd: Any) -> str:
    code = str(stk_cd).strip()
    # Kiwoom 잔고/주문 응답은 종목코드 앞에 A가 붙는 경우가 있습니다.
    # 알파벳이 포함된 ETF/ETN 코드가 손상되지 않도록 선행 A만 제거합니다.
    return code[1:] if code.startswith("A") else code


def _target_by_code(stk_cd: str) -> dict[str, Any]:
    code = _norm_code(stk_cd)
    for target in TARGET_STOCKS:
        if _norm_code(target.get("code")) == code:
            return target
    return {
        "code": code,
        "name": code,
        "weight": 0.0,
        "take_profit_pct": 4.0,
        "stop_loss_pct": 3.0,
        "take_profit_schedule": [4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
        "stop_loss_schedule": [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5],
        "test_down_rate": 0.01,
        "test_sellable_qty": 10,
    }


def _target_name(stk_cd: str) -> str:
    return str(_target_by_code(stk_cd).get("name", _norm_code(stk_cd)))


def _take_profit_pct(stk_cd: str) -> float:
    return float(_target_by_code(stk_cd).get("take_profit_pct", 12.0))


def _take_profit_pct_by_cycle(stk_cd: str, cycle_count: int = 0) -> float:
    """회차별 익절률을 반환합니다.

    단타 수수료 부담 때문에 기본 전략은 익절률을 고정합니다.
    KEEP_TAKE_PROFIT_FIXED_ON_STOP_RESET=False 로 바꾸면 기존 schedule 방식으로 동작합니다.
    """
    if KEEP_TAKE_PROFIT_FIXED_ON_STOP_RESET:
        return _take_profit_pct(stk_cd)

    target = _target_by_code(stk_cd)
    schedule = target.get("take_profit_schedule", DEFAULT_TAKE_PROFIT_SCHEDULE)
    try:
        if schedule:
            idx = max(0, min(int(cycle_count), len(schedule) - 1))
            return float(schedule[idx])
    except Exception:
        pass
    return _take_profit_pct(stk_cd)


def _stop_loss_pct(stk_cd: str) -> float:
    return float(_target_by_code(stk_cd).get("stop_loss_pct", 6.0))


def _stop_loss_pct_by_cycle(stk_cd: str, cycle_count: int = 0) -> float:
    """DCA트리거 재설정 회차에 따라 DCA트리거폭을 반환합니다.

    예: 2.0 → 2.5 → 3.0 ... 처럼 DCA트리거폭만 넓혀 매매 횟수를 줄이고,
    단기 반등을 기다리는 구조입니다.
    """
    target = _target_by_code(stk_cd)
    schedule = target.get("stop_loss_schedule", DEFAULT_STOP_LOSS_SCHEDULE)
    try:
        if schedule:
            idx = max(0, min(int(cycle_count), len(schedule) - 1))
            return float(schedule[idx])
    except Exception:
        pass
    return _stop_loss_pct(stk_cd)


def _test_down_rate(stk_cd: str) -> float:
    return float(_target_by_code(stk_cd).get("test_down_rate", 0.01))


def _test_sellable_qty(stk_cd: str, default_qty: int = 0) -> int:
    if default_qty and default_qty > 0:
        return int(default_qty)
    return int(_target_by_code(stk_cd).get("test_sellable_qty", 0) or 0)


def _is_valid_order_no(ord_no: Any) -> bool:
    """Kiwoom 주문번호가 실제 주문번호처럼 보이는지 검사합니다."""
    if ord_no is None:
        return False
    text = str(ord_no).strip()
    if not text:
        return False
    if text.startswith("TEST_"):
        return True
    bad_words = ("없습니다", "실패", "ERROR", "Error", "error", "return_code", "return_msg")
    if any(word in text for word in bad_words):
        return False
    # 키움 주문번호는 보통 숫자 문자열입니다. 앞자리 0은 허용합니다.
    return text.isdigit()


def _require_valid_order_no(ord_no: Any, context: str) -> str:
    if not _is_valid_order_no(ord_no):
        raise RuntimeError(f"{context} 실패: 유효한 주문번호가 아닙니다. 응답={ord_no}")
    return str(ord_no).strip()


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return (
        "HTTP 429" in text
        or "허용된 요청 개수" in text
        or "return_code\":5" in text
        or "return_code': 5" in text
    )


def _wait_order_api_slot(label: str = "주문 API") -> None:
    """주문/취소 API를 너무 촘촘하게 호출하지 않도록 최소 간격을 보장합니다."""
    global _LAST_ORDER_API_TS
    if TEST_MODE:
        return

    now_ts = time.time()
    wait_sec = ORDER_API_MIN_INTERVAL_SEC - (now_ts - _LAST_ORDER_API_TS)
    if wait_sec > 0:
        print(f"[{_now()}] {label} 연속 호출 방지 대기 {wait_sec:.1f}초")
        time.sleep(wait_sec)

    _LAST_ORDER_API_TS = time.time()


def _call_order_api_with_retry(label: str, func, *args, **kwargs):
    """HTTP 429가 나면 잠시 대기 후 같은 주문 API를 재시도합니다."""
    last_exc: Exception | None = None
    for attempt in range(1, ORDER_API_429_RETRY_COUNT + 1):
        try:
            _wait_order_api_slot(label)
            result = func(*args, **kwargs)
            return result
        except Exception as exc:
            last_exc = exc
            if not _is_rate_limit_error(exc):
                raise
            if attempt >= ORDER_API_429_RETRY_COUNT:
                break
            sleep_sec = ORDER_API_429_RETRY_SLEEP_SEC * attempt
            print(
                f"[{_now()}] {label} 요청 제한(429) / {attempt}회차 실패 / "
                f"{sleep_sec:.1f}초 후 재시도: {exc}"
            )
            time.sleep(sleep_sec)

    raise RuntimeError(f"{label} 요청 제한 재시도 실패: {last_exc}")


def _calc_take_profit_price(stk_cd: str, buy_price: int, cycle_count: int = 0) -> int:
    pct = _take_profit_pct_by_cycle(stk_cd, cycle_count)
    return floor_to(int(buy_price * (1 + pct / 100.0)), PRICE_UNIT)


def _calc_take_profit_price_with_pct(buy_price: int, pct: float) -> int:
    return floor_to(int(buy_price * (1 + pct / 100.0)), PRICE_UNIT)


def _calc_stop_loss_price(stk_cd: str, buy_price: int, cycle_count: int = 0) -> int:
    pct = _stop_loss_pct_by_cycle(stk_cd, cycle_count)
    return floor_to(int(buy_price * (1 - pct / 100.0)), PRICE_UNIT)


def _calc_limit_buy_price(stk_cd: str, now_price: int) -> int:
    """지정가 매수 주문가격을 계산합니다.

    현재가보다 약간 높은 지정가를 사용하면 시장가처럼 즉시 체결될 가능성을 높이면서도
    증거금은 지정가 기준으로 잡혀 남는 현금을 줄일 수 있습니다.
    """
    if now_price <= 0:
        return 0
    price = int(now_price * (1 + LIMIT_BUY_UP_PCT / 100.0))
    # 매수 지정가는 너무 낮게 내려가지 않도록 ceil_to로 호가 단위 올림 처리합니다.
    try:
        return int(math.ceil(price / PRICE_UNIT) * PRICE_UNIT)
    except Exception:
        return price


def _buy_order_type() -> str:
    order_type = str(BUY_ORDER_TYPE or "MARKET").strip().upper()
    if order_type not in ("MARKET", "LIMIT"):
        print(f"[{_now()}] BUY_ORDER_TYPE={BUY_ORDER_TYPE!r} 값이 올바르지 않아 MARKET으로 처리합니다.")
        return "MARKET"
    return order_type


def _today_at_hhmm(hhmm: str) -> datetime | None:
    try:
        hh, mm = map(int, str(hhmm).strip().split(":"))
        return datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        print(f"[{_now()}] FORCE_EXIT_TIME={hhmm!r} 형식이 잘못되었습니다. 예: 14:30")
        return None


def _force_exit_time_reached() -> bool:
    if not FORCE_EXIT_ENABLED:
        return False
    target = _today_at_hhmm(FORCE_EXIT_TIME)
    return bool(target and datetime.now() >= target)


def _print_force_exit_header() -> None:
    print("\n" + "=" * 72)
    print(f"[{_now()}] 마감 청산 시간 도달: FORCE_EXIT_TIME={FORCE_EXIT_TIME}")
    print("=" * 72)


def _print_account_after_liquidation(client: KiwoomClient) -> None:
    try:
        snapshot = _get_account_snapshot(client)
        _print_account_snapshot(snapshot)
    except Exception as exc:
        print(f"[{_now()}] 청산 후 계좌 정보 조회 실패: {exc}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KODEX 단일종목레버리지 DCA 매수, 익절 등록, DCA 감시 APP")
    parser.add_argument(
        "--restore",
        nargs="*",
        default=[],
        metavar="CODE:BUY_PRICE",
        help="강제 종료 후 재시작 모드. 예: --restore 0193T0:10000 0193W0:10000",
    )
    parser.add_argument(
        "--restart",
        nargs="*",
        default=[],
        metavar="CODE:BUY_PRICE",
        help="--restore와 동일합니다. 기존 습관용 alias입니다.",
    )
    parser.add_argument("--yes", action="store_true", help="모든 확인 질문 없이 바로 실행합니다. 일반 매수/재시작/전체매도에 모두 적용됩니다.")
    parser.add_argument("--sell-all", action="store_true", help="현재 보유 중인 모든 종목의 매도가능수량을 시장가로 매도하고 종료합니다. 초기화용입니다.")
    parser.add_argument("--log", default="", metavar="FILE", help="화면 출력 내용을 지정한 txt 파일에도 함께 저장합니다. 예: --log 260626.txt")
    return parser.parse_args()


def _parse_restore_args(values: list[str]) -> list[dict[str, Any]]:
    restore_items: list[dict[str, Any]] = []
    for raw in values:
        raw = str(raw).strip()
        if not raw:
            continue
        parts = raw.split(":")
        if len(parts) != 2:
            raise SystemExit("복구 형식이 잘못되었습니다. 예: --restore 0193T0:10000 0193W0:10000")
        code, buy_price = parts
        code = _norm_code(code)
        buy_price_int = _safe_int(buy_price)
        if not code or buy_price_int <= 0:
            raise SystemExit(f"복구 값이 잘못되었습니다: {raw}. 형식: 종목코드:매입가")
        restore_items.append({"code": code, "buy_price": buy_price_int})
    return restore_items


# ===============================
# 계좌 / 잔고 / 출력
# ===============================

def _get_account_snapshot(client: KiwoomClient) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}

    for method_name in ("get_account_info", "get_account_balance", "get_balance"):
        if hasattr(client, method_name):
            try:
                data = getattr(client, method_name)()
                if isinstance(data, dict):
                    snapshot.update(data)
                else:
                    snapshot[method_name] = data
                break
            except Exception as exc:
                snapshot[f"{method_name}_error"] = str(exc)

    cur_entr = client.get_current_entr()
    snapshot["cur_entr"] = _safe_int(cur_entr)
    return snapshot


def _print_account_snapshot(snapshot: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print(f"[{_now()}] 계좌 정보")
    print("=" * 72)

    cur_entr = _safe_int(snapshot.get("cur_entr"))
    print(f"주문가능금액: {format(cur_entr, ',')}원")

    for key, value in snapshot.items():
        if key == "cur_entr":
            continue
        print(f"{key}: {value}")


def _get_balance_map(client: KiwoomClient, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """잔고 전체를 1회 조회하여 종목코드별로 매핑합니다.

    kt00018은 짧은 시간에 반복 호출하면 HTTP 429가 발생할 수 있으므로 캐시를 사용합니다.
    조회 실패 시 기존 캐시가 있으면 캐시를 반환하여 DCA 감시가 바로 종료되지 않도록 합니다.
    """
    global _LAST_BALANCE_MAP, _LAST_BALANCE_TS

    if TEST_MODE:
        return {}

    if not hasattr(client, "get_my_all_stock"):
        print(f"[{_now()}] KiwoomClient에 get_my_all_stock() 함수가 없어 잔고를 확인할 수 없습니다.")
        return _LAST_BALANCE_MAP

    now_ts = time.time()
    if (
        not force_refresh
        and _LAST_BALANCE_MAP
        and (now_ts - _LAST_BALANCE_TS) < BALANCE_QUERY_MIN_INTERVAL_SEC
    ):
        return _LAST_BALANCE_MAP

    try:
        balance_info = client.get_my_all_stock()
    except Exception as exc:
        print(f"[{_now()}] 잔고 전체 조회 실패: {exc}")
        if _LAST_BALANCE_MAP:
            print(f"[{_now()}] 잔고 조회 실패로 직전 잔고 캐시를 사용합니다. DCA 감시는 유지합니다.")
        return _LAST_BALANCE_MAP

    result: dict[str, dict[str, Any]] = {}
    for stock in balance_info or []:
        code = _norm_code(stock.get("stk_cd", ""))
        if code:
            result[code] = stock

    _LAST_BALANCE_MAP = result
    _LAST_BALANCE_TS = now_ts
    return result

def _sellable_qty_from_balance_map(balance_map: dict[str, dict[str, Any]], stk_cd: str) -> int:
    stock = balance_map.get(_norm_code(stk_cd))
    if not stock:
        return 0
    return _safe_int(stock.get("trde_able_qty"), 0)


def _holding_qty_from_stock(stock: dict[str, Any]) -> int:
    """잔고 응답에서 보유수량을 최대한 보수적으로 읽습니다."""
    if not stock:
        return 0
    # Kiwoom 응답명은 구현마다 다를 수 있어 후보 키를 넓게 둡니다.
    keys = (
        "hold_qty", "hldg_qty", "rmnd_qty", "stk_qty", "qty",
        "jan_qty", "bal_qty", "poss_qty", "ord_psbl_qty", "trde_able_qty",
    )
    vals = [_safe_int(stock.get(k), 0) for k in keys if k in stock]
    if vals:
        max_qty = max(vals)
        # 익절 지정가 주문으로 매도가능수량이 0이어도 잔고 행이 존재하면 보유 중일 수 있습니다.
        # 보유수량 키를 정확히 알 수 없는 경우 감시를 바로 끊지 않기 위해 1주 보유로 간주합니다.
        return max_qty if max_qty > 0 else 1
    return 1 if stock else 0


def _holding_qty_from_balance_map(balance_map: dict[str, dict[str, Any]], stk_cd: str) -> int:
    stock = balance_map.get(_norm_code(stk_cd))
    return _holding_qty_from_stock(stock or {})


def _get_sellable_qty(client: KiwoomClient, stk_cd: str, default_qty: int = 0) -> int:
    """계좌 잔고에서 해당 종목의 매도가능수량만 조회합니다. TEST에서는 가상 수량을 사용합니다."""
    target_code = _norm_code(stk_cd)

    if TEST_MODE:
        fake_qty = _test_sellable_qty(target_code, default_qty)
        print(f"[{_now()}] [TEST] {target_code} 매도가능수량을 가상값 {fake_qty}주로 사용합니다.")
        return fake_qty

    balance_map = _get_balance_map(client)
    return _sellable_qty_from_balance_map(balance_map, target_code)


def _wait_sellable_qty(
    client: KiwoomClient,
    stk_cd: str,
    expected_qty: int,
    timeout_sec: float = 20.0,
    poll_sec: float = 3.0,
) -> int:
    """
    시장가 매수 체결 직후 잔고/매도가능수량 반영이 늦을 수 있어 잠시 기다립니다.
    익절 지정가 매도 등록 전 매도가능수량을 확인하여 '매도가능수량 부족'을 줄입니다.
    """
    target_code = _norm_code(stk_cd)

    if TEST_MODE:
        return _test_sellable_qty(target_code, expected_qty)

    deadline = time.time() + timeout_sec
    last_qty = 0
    poll_count = 0
    while time.time() < deadline:
        poll_count += 1
        balance_map = _get_balance_map(client, force_refresh=True)
        last_qty = _sellable_qty_from_balance_map(balance_map, target_code)
        print(
            f"[{_now()}] {target_code} 매도가능수량 반영 대기 {poll_count}회차 / "
            f"확인수량 {last_qty}주 / 기대수량 {expected_qty}주"
        )
        if last_qty > 0:
            return min(last_qty, expected_qty) if expected_qty > 0 else last_qty
        time.sleep(poll_sec)

    return last_qty


def _make_order_plan(client: KiwoomClient, cur_entr: int) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []

    for target in TARGET_STOCKS:
        stk_cd = _norm_code(target["code"])
        stk_nm = str(target["name"])
        weight = float(target["weight"])
        budget = math.floor(cur_entr * INITIAL_ENTRY_CASH_RATE * weight)

        now_price = int(client.get_last_price(stk_cd))
        time.sleep(1)

        buy_order_type = _buy_order_type()
        planned_buy_price = _calc_limit_buy_price(stk_cd, now_price) if buy_order_type == "LIMIT" else now_price
        qty = int(budget // planned_buy_price) if planned_buy_price > 0 else 0
        expected_amount = qty * planned_buy_price
        remaining_budget = budget - expected_amount
        expected_take_profit_price = _calc_take_profit_price(stk_cd, planned_buy_price)
        expected_stop_loss_price = _calc_stop_loss_price(stk_cd, planned_buy_price)

        plans.append(
            {
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "weight": weight,
                "budget": budget,
                "dca_reserve_budget": math.floor(cur_entr * DCA_RESERVE_CASH_RATE * weight),
                "now_price": now_price,
                "planned_buy_price": planned_buy_price,
                "buy_order_type": buy_order_type,
                "qty": qty,
                "expected_amount": expected_amount,
                "remaining_budget": remaining_budget,
                "take_profit_pct": _take_profit_pct(stk_cd),
                "stop_loss_pct": _stop_loss_pct(stk_cd),
                "expected_take_profit_price": expected_take_profit_price,
                "expected_stop_loss_price": expected_stop_loss_price,
            }
        )

    return plans


def _print_order_plan(plans: list[dict[str, Any]], cur_entr: int) -> None:
    print("\n" + "=" * 72)
    print("최초 50% 진입 + 50% DCA 예산 실행 전 예상 매수 내역")
    print("=" * 72)

    total_expected = 0
    for plan in plans:
        total_expected += int(plan["expected_amount"])
        print(
            f"{plan['stk_nm']}[{plan['stk_cd']}] "
            f"비중 {plan['weight'] * 100:.0f}% / "
            f"최초진입예산 {format(plan['budget'], ',')}원 / DCA예비예산 {format(plan.get('dca_reserve_budget', 0), ',')}원 / "
            f"현재가 {format(plan['now_price'], ',')}원 / "
            f"매수방식 {plan.get('buy_order_type', 'MARKET')} / "
            f"주문기준가 {format(plan.get('planned_buy_price', plan['now_price']), ',')}원 / "
            f"예상수량 {plan['qty']}주 / "
            f"예상매수금액 {format(plan['expected_amount'], ',')}원 / "
            f"익절 {plan['take_profit_pct']:.1f}% -> {format(plan['expected_take_profit_price'], ',')}원 / "
            f"DCA트리거 {plan['stop_loss_pct']:.1f}% -> {format(plan['expected_stop_loss_price'], ',')}원"
        )

    print("-" * 72)
    print(f"총 예상 매수금액: {format(total_expected, ',')}원")
    print(f"예상 최초 진입 후 DCA/잔여 주문가능금액: {format(cur_entr - total_expected, ',')}원")
    if _buy_order_type() == "LIMIT":
        print(f"※ 지정가 매수 방식입니다. 주문기준가는 현재가 +{LIMIT_BUY_UP_PCT:.2f}%를 호가단위로 올림한 가격입니다.")
        print("※ 지정가보다 시장가격이 높으면 미체결될 수 있습니다.")
    else:
        print("※ 시장가 주문이므로 실제 체결금액은 현재가 기준 예상금액과 달라질 수 있습니다.")
    print("※ 익절 지정가 매도는 주문 등록합니다.")
    print("※ DCA트리거은 예약 등록이 아니라 감시 후 조건 충족 시 해당 종목만 시장가 매도합니다.")


def _confirm_execution(message: str) -> bool:
    while True:
        answer = input(f"\n{message} [Y/N]: ").strip().upper()
        if answer in ("Y", "YES"):
            return True
        if answer in ("N", "NO"):
            return False
        print("Y 또는 N으로 입력해 주세요.")


# ===============================
# 주문 함수
# ===============================


# ===============================
# 미체결 주문 조회/취소 보조 함수
# ===============================

def _first_present(data: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in data and data.get(key) not in (None, ""):
            return data.get(key)
    return default


def _extract_order_rows(data: Any) -> list[dict[str, Any]]:
    """여러 형태의 미체결 조회 응답에서 주문 row dict만 최대한 추출합니다."""
    rows: list[dict[str, Any]] = []

    if isinstance(data, list):
        for item in data:
            rows.extend(_extract_order_rows(item))
        return rows

    if not isinstance(data, dict):
        return rows

    # 이 dict 자체가 주문 row인지 확인
    possible_ord_no = _first_present(
        data,
        (
            "ord_no", "order_no", "ordNo", "odno", "orgn_ord_no", "orig_ord_no",
            "주문번호", "원주문번호",
        ),
    )
    possible_code = _first_present(data, ("stk_cd", "stock_code", "code", "종목코드"))
    if possible_ord_no and possible_code:
        rows.append(data)

    # 응답 안의 list/dict 재귀 탐색
    for value in data.values():
        if isinstance(value, (list, dict)):
            rows.extend(_extract_order_rows(value))

    # 중복 제거
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        ord_no = str(_first_present(row, ("ord_no", "order_no", "ordNo", "odno", "orgn_ord_no", "orig_ord_no", "주문번호", "원주문번호"), "")).strip()
        code = _norm_code(_first_present(row, ("stk_cd", "stock_code", "code", "종목코드"), ""))
        key = (ord_no, code)
        if ord_no and key not in seen:
            seen.add(key)
            unique.append(row)
    return unique



def _query_unfilled_orders_rest(
    client: KiwoomClient,
    stk_cd: str = "",
    trde_tp: str = "0",
) -> list[dict[str, Any]]:
    """
    Kiwoom REST 미체결요청을 직접 호출합니다.

    중요:
    기존 kt00007 응답이 0건으로 나오는 환경이 있어 ka10075도 함께 시도합니다.
    키움 REST 국내주식 계좌 미체결요청은 보통 다음 body를 사용합니다.
    - all_stk_tp: 0 전체, 1 종목
    - trde_tp: 0 전체, 1 매도, 2 매수
    - stk_cd: all_stk_tp=1일 때 종목코드
    - stex_tp: 0 통합, 1 KRX, 2 NXT
    """
    if not hasattr(client, "_post"):
        return []

    code = _norm_code(stk_cd) if stk_cd else ""
    all_stk_tp = "1" if code else "0"

    # ka10075가 실제 미체결요청에 맞는 경우가 많습니다.
    # kt00007은 기존 코드와 호환을 위해 뒤쪽 후보로만 유지합니다.
    candidates = [
        ("/api/dostk/acnt", "ka10075", {"all_stk_tp": all_stk_tp, "trde_tp": trde_tp, "stk_cd": code, "stex_tp": "0"}),
        ("/api/dostk/acnt", "ka10075", {"all_stk_tp": all_stk_tp, "trde_tp": trde_tp, "stk_cd": code, "stex_tp": "1"}),
        ("/api/dostk/acnt", "kt00007", {"all_stk_tp": all_stk_tp, "trde_tp": trde_tp, "stk_cd": code, "stex_tp": "0"}),
        ("/api/dostk/acnt", "kt00007", {"all_stk_tp": all_stk_tp, "trde_tp": trde_tp, "stk_cd": code, "stex_tp": "1"}),
        ("/api/dostk/acnt", "kt00007", {"qry_tp": "0", "dmst_stex_tp": "KRX"}),
        ("/api/dostk/acnt", "kt00007", {"dmst_stex_tp": "KRX"}),
    ]

    last_error: Exception | None = None
    for path, api_id, body in candidates:
        try:
            response = client._post(path, api_id=api_id, body=body)
            rows = _extract_order_rows(response)
            if rows:
                print(
                    f"[{_now()}] 미체결 조회 성공 / API {api_id} "
                    f"/ 종목 {code or '전체'} / 매매구분 {trde_tp} / {len(rows)}건"
                )
                return rows
        except Exception as exc:
            last_error = exc

    # 반복 감시 중에는 0건/429 로그가 너무 많아지므로 호출부에서 필요한 메시지만 출력합니다.
    return []

def _query_unfilled_orders(client: KiwoomClient) -> list[dict[str, Any]]:
    """
    미체결 주문 목록을 조회합니다.
    프로젝트별 KiwoomClient 함수명이 다를 수 있어 흔한 함수명을 먼저 시도하고,
    없으면 REST _post를 보수적으로 시도합니다.
    """
    if TEST_MODE:
        return []

    method_names = (
        "get_unfilled_orders",
        "get_pending_orders",
        "get_not_concluded_orders",
        "get_unexecuted_orders",
        "get_open_orders",
        "get_order_unfilled",
    )

    last_error: Exception | None = None
    for method_name in method_names:
        if not hasattr(client, method_name):
            continue
        method = getattr(client, method_name)
        try:
            response = method()
            rows = _extract_order_rows(response)
            print(f"[{_now()}] 미체결 조회 {method_name} 사용 / {len(rows)}건")
            return rows
        except Exception as exc:
            last_error = exc
            print(f"[{_now()}] 미체결 조회 {method_name} 실패: {exc}")

    # Kiwoom REST 국내주식 계좌 미체결 직접 호출.
    rows = _query_unfilled_orders_rest(client, stk_cd="", trde_tp="0")
    if rows:
        return rows

    if last_error:
        print(f"[{_now()}] 미체결 주문 조회 실패. 사용 가능한 조회 함수가 없거나 API 응답 실패: {last_error}")
    else:
        print(f"[{_now()}] 미체결 주문 조회 함수를 찾지 못했습니다. get_unfilled_orders() 계열 함수를 KiwoomClient에 추가하면 자동 취소가 가능합니다.")
    return []


def _unfilled_order_no(row: dict[str, Any]) -> str:
    return str(_first_present(row, ("ord_no", "order_no", "ordNo", "odno", "orgn_ord_no", "orig_ord_no", "주문번호", "원주문번호"), "")).strip()


def _unfilled_stock_code(row: dict[str, Any]) -> str:
    return _norm_code(_first_present(row, ("stk_cd", "stock_code", "code", "종목코드"), ""))


def _unfilled_remain_qty(row: dict[str, Any]) -> int:
    return _safe_int(
        _first_present(
            row,
            (
                "rmn_qty", "remain_qty", "unfilled_qty", "ord_rem_qty", "remn_qty",
                "미체결수량", "주문잔량", "잔량", "ord_qty", "order_qty", "주문수량",
            ),
            0,
        ),
        0,
    )


def _unfilled_order_type_text(row: dict[str, Any]) -> str:
    return str(
        _first_present(
            row,
            ("ord_dvsn", "ord_tp", "order_type", "trde_tp", "sll_buy_dvsn_cd", "buy_sell", "매매구분", "주문구분"),
            "",
        )
    )


def _is_sell_unfilled(row: dict[str, Any]) -> bool:
    text = _unfilled_order_type_text(row).lower()
    if any(token in text for token in ("매도", "sell", "sll", "2")):
        return True
    if any(token in text for token in ("매수", "buy", "bid", "1")):
        return False
    # 구분값을 못 읽으면 보수적으로 True 취급합니다. 취소 대상 필터는 호출부가 결정합니다.
    return True


def _cancel_order_generic(client: KiwoomClient, ord_no: str, stk_cd: str, qty: int) -> Any:
    """미체결 주문 취소. 기존 프로젝트 함수명 우선 사용."""
    if TEST_MODE:
        return "TEST_CANCEL_ORDER_SKIPPED"

    if hasattr(client, "place_sell_order_cancel"):
        return client.place_sell_order_cancel(str(ord_no), stk_cd, qty)

    if hasattr(client, "cancel_order"):
        try:
            return client.cancel_order(ord_no=str(ord_no), stk_cd=stk_cd, qty=qty)
        except TypeError:
            return client.cancel_order(str(ord_no), stk_cd, qty)

    if hasattr(client, "cancel_sell_order"):
        return client.cancel_sell_order(ord_no=str(ord_no), stk_cd=stk_cd, qty=qty)

    raise AttributeError("KiwoomClient에 주문 취소 함수가 없습니다. place_sell_order_cancel(ord_no, stk_cd, qty) 또는 cancel_order()가 필요합니다.")


def _cancel_unfilled_orders(
    client: KiwoomClient,
    target_codes: set[str] | None = None,
    only_sell_orders: bool = False,
    reason: str = "",
) -> list[dict[str, Any]]:
    """미체결 주문을 조회하여 조건에 맞는 주문을 취소합니다."""
    target_codes_norm = {_norm_code(code) for code in target_codes} if target_codes else None

    rows = _query_unfilled_orders(client)
    results: list[dict[str, Any]] = []

    if not rows:
        print(f"[{_now()}] 취소할 미체결 주문이 없습니다. {reason}".rstrip())
        return results

    for row in rows:
        ord_no = _unfilled_order_no(row)
        stk_cd = _unfilled_stock_code(row)
        qty = _unfilled_remain_qty(row)

        if not ord_no or not stk_cd:
            continue
        if target_codes_norm and stk_cd not in target_codes_norm:
            continue
        if only_sell_orders and not _is_sell_unfilled(row):
            continue
        if qty <= 0:
            qty = 0

        try:
            cancel_result = _cancel_order_generic(client, ord_no=ord_no, stk_cd=stk_cd, qty=qty)
            print(f"[{_now()}] 미체결 취소 접수 / {stk_cd} / 주문번호 {ord_no} / 잔량 {qty} / 결과 {cancel_result}")
            results.append({"stk_cd": stk_cd, "ord_no": ord_no, "qty": qty, "cancel_result": cancel_result})
        except Exception as exc:
            print(f"[{_now()}] 미체결 취소 실패 / {stk_cd} / 주문번호 {ord_no} / 잔량 {qty} / {exc}")
            results.append({"stk_cd": stk_cd, "ord_no": ord_no, "qty": qty, "error": str(exc)})

    if results:
        time.sleep(ORDER_CANCEL_WAIT_SEC)
        _get_balance_map(client, force_refresh=True)
    return results




def _cancel_unfilled_orders_for_holdings(
    client: KiwoomClient,
    holding_codes: set[str],
    reason: str = "",
) -> list[dict[str, Any]]:
    """
    전체 미체결 조회가 0건으로 나와도 보유종목별 미체결 매도 주문을 한 번 더 조회/취소합니다.
    익절 지정가 주문이 걸려 있으면 잔고상 매도가능수량이 0이 되므로,
    sell-all/DCA트리거 전에는 이 보조 경로가 중요합니다.
    """
    results: list[dict[str, Any]] = []
    for code in sorted({_norm_code(c) for c in holding_codes if c}):
        rows = _query_unfilled_orders_rest(client, stk_cd=code, trde_tp="1")
        if not rows:
            rows = _query_unfilled_orders_rest(client, stk_cd=code, trde_tp="0")

        for row in rows:
            ord_no = _unfilled_order_no(row)
            stk_cd = _unfilled_stock_code(row) or code
            qty = _unfilled_remain_qty(row)
            if not ord_no:
                continue
            if _norm_code(stk_cd) != code:
                continue
            if not _is_sell_unfilled(row):
                continue

            try:
                cancel_result = _cancel_order_generic(client, ord_no=ord_no, stk_cd=code, qty=qty)
                print(
                    f"[{_now()}] 보유종목별 미체결 매도 취소 접수 / "
                    f"{code} / 주문번호 {ord_no} / 잔량 {qty} / 결과 {cancel_result}"
                )
                results.append({"stk_cd": code, "ord_no": ord_no, "qty": qty, "cancel_result": cancel_result})
            except Exception as exc:
                print(f"[{_now()}] 보유종목별 미체결 매도 취소 실패 / {code} / 주문번호 {ord_no} / {exc}")
                results.append({"stk_cd": code, "ord_no": ord_no, "qty": qty, "error": str(exc)})

        # 종목별 조회가 API 과호출로 막히지 않게 약간 간격을 둡니다.
        time.sleep(0.5)

    if results:
        time.sleep(ORDER_CANCEL_WAIT_SEC)
        _get_balance_map(client, force_refresh=True)
    else:
        print(f"[{_now()}] 보유종목별 미체결 매도 취소 대상이 없습니다. {reason}".rstrip())
    return results


def _cancel_before_sell_by_codes(
    client: KiwoomClient,
    target_codes: set[str],
    reason: str,
) -> list[dict[str, Any]]:
    """시장가 매도 전 미체결 매도 주문을 최대한 찾아 취소합니다."""
    if TEST_MODE:
        print(f"[{_now()}] [TEST] 시장가 매도 전 미체결 취소 생략 / {reason}")
        return []

    results = _cancel_unfilled_orders(
        client,
        target_codes=target_codes,
        only_sell_orders=True,
        reason=reason,
    )

    # 전체 미체결 조회가 0건이어도 잔고 매도가능수량이 0이면 익절 주문이 숨어 있을 수 있습니다.
    # 보유 종목별 ka10075 조회로 한 번 더 확인합니다.
    extra = _cancel_unfilled_orders_for_holdings(client, target_codes, reason=reason)
    results.extend(extra)
    return results

def _place_take_profit_sell(client: KiwoomClient, stk_cd: str, qty: int, sell_price: int) -> dict[str, Any]:
    """지정가 익절 매도 주문을 등록합니다."""
    if qty <= 0:
        return {"sell_ord_no": None, "qty": qty, "price": sell_price, "reason": "qty <= 0"}

    if TEST_MODE:
        sell_ord_no = "TEST_TAKE_PROFIT_NOT_SENT"
        print(
            f"[{_now()}] [TEST] {stk_cd} 실제 익절 지정가 주문 생략 / "
            f"가상주문번호 {sell_ord_no} / 수량 {qty}주 / 가격 {format(sell_price, ',')}원"
        )
        return {"sell_ord_no": sell_ord_no, "qty": qty, "price": sell_price, "method": "test_place_sell_limit_skipped"}

    if hasattr(client, "place_sell_limit"):
        sell_ord_no = _call_order_api_with_retry(
            f"{stk_cd} 익절 지정가 매도",
            client.place_sell_limit,
            stk_cd=stk_cd,
            qty=qty,
            price=sell_price,
        )
        sell_ord_no = _require_valid_order_no(sell_ord_no, f"{stk_cd} 익절 지정가 매도 주문")
        return {"sell_ord_no": sell_ord_no, "qty": qty, "price": sell_price, "method": "place_sell_limit"}

    if hasattr(client, "place_limit_sell"):
        result = _call_order_api_with_retry(
            f"{stk_cd} 익절 지정가 매도",
            client.place_limit_sell,
            stk_cd=stk_cd,
            qty=qty,
            price=sell_price,
        )
        return {"sell_ord_no": result, "qty": qty, "price": sell_price, "method": "place_limit_sell"}

    if hasattr(client, "place_limit_sell_order"):
        result = _call_order_api_with_retry(
            f"{stk_cd} 익절 지정가 매도",
            client.place_limit_sell_order,
            stk_cd=stk_cd,
            qty=qty,
            price=sell_price,
        )
        return {"sell_ord_no": result, "qty": qty, "price": sell_price, "method": "place_limit_sell_order"}

    if hasattr(client, "place_sell_order"):
        result = _call_order_api_with_retry(
            f"{stk_cd} 익절 지정가 매도",
            client.place_sell_order,
            stk_cd=stk_cd,
            qty=qty,
            price=sell_price,
            hoga_gb="00",
        )
        return {"sell_ord_no": result, "qty": qty, "price": sell_price, "method": "place_sell_order"}

    raise AttributeError("KiwoomClient에 지정가 매도 함수가 없습니다. place_sell_limit(stk_cd, qty, price)를 확인하세요.")


def _place_buy_market_raw(client: KiwoomClient, stk_cd: str, qty: int) -> Any:
    """KiwoomClient.place_buy_market()이 오류 원문을 숨길 때를 대비한 직접 주문 호출."""
    if not hasattr(client, "_post"):
        return client.place_buy_market(stk_cd=stk_cd, qty=qty)

    tcode = _norm_code(stk_cd)
    body = {
        "dmst_stex_tp": "KRX",
        "stk_cd": tcode,
        "ord_qty": f"{qty}",
        "ord_uv": "",
        "trde_tp": "3",
        "cond_uv": "",
    }
    data = client._post("/api/dostk/ordr", api_id="kt10000", body=body)
    if isinstance(data, dict):
        return data
    return data




def _place_buy_limit_raw(client: KiwoomClient, stk_cd: str, qty: int, price: int) -> Any:
    """지정가 매수 주문. KiwoomClient에 함수가 있으면 우선 사용하고, 없으면 REST 직접 호출을 시도합니다."""
    if hasattr(client, "place_buy_limit"):
        return client.place_buy_limit(stk_cd=stk_cd, qty=qty, price=price)

    if hasattr(client, "place_limit_buy"):
        return client.place_limit_buy(stk_cd=stk_cd, qty=qty, price=price)

    if hasattr(client, "place_buy_order"):
        try:
            return client.place_buy_order(stk_cd=stk_cd, qty=qty, price=price, hoga_gb="00")
        except TypeError:
            pass

    if not hasattr(client, "_post"):
        raise AttributeError("KiwoomClient에 지정가 매수 함수가 없습니다. place_buy_limit(stk_cd, qty, price)를 추가하세요.")

    tcode = _norm_code(stk_cd)
    body = {
        "dmst_stex_tp": "KRX",
        "stk_cd": tcode,
        "ord_qty": f"{qty}",
        "ord_uv": f"{price}",
        "trde_tp": "0",  # 지정가
        "cond_uv": "",
    }
    data = client._post("/api/dostk/ordr", api_id="kt10000", body=body)
    return data


def _place_buy_limit_with_retry(client: KiwoomClient, stk_cd: str, qty: int, price: int) -> tuple[str, int, int]:
    last_response: Any = None
    order_qty = int(qty)
    order_price = int(price)

    for attempt in range(1, LIMIT_BUY_RETRY_COUNT + 2):
        if order_qty <= 0:
            raise RuntimeError(f"{stk_cd} 지정가 매수 가능 수량이 0주입니다.")
        if order_price <= 0:
            raise RuntimeError(f"{stk_cd} 지정가 매수 가격이 0원입니다.")

        try:
            response = _place_buy_limit_raw(client, stk_cd=stk_cd, qty=order_qty, price=order_price)
            last_response = response
            ord_no = _extract_order_no(response)
            if _is_valid_order_no(ord_no):
                if attempt > 1:
                    print(f"[{_now()}] {stk_cd} 지정가 매수 재시도 성공 / {attempt}회차 / 주문수량 {order_qty}주 / 주문가 {format(order_price, ',')}원 / 주문번호 {ord_no}")
                return str(ord_no).strip(), order_qty, order_price
            print(f"[{_now()}] {stk_cd} 지정가 매수 주문번호 비정상 / {attempt}회차 / 주문수량 {order_qty}주 / 주문가 {format(order_price, ',')}원 / 응답={response}")
        except Exception as exc:
            last_response = exc
            print(f"[{_now()}] {stk_cd} 지정가 매수 주문 예외 / {attempt}회차 / 주문수량 {order_qty}주 / 주문가 {format(order_price, ',')}원 / {exc}")

        if attempt > LIMIT_BUY_RETRY_COUNT:
            break

        try:
            cur_entr = _safe_int(client.get_current_entr(), 0)
            if cur_entr > 0 and order_price > 0:
                safe_qty = int(cur_entr // order_price)
                if 0 < safe_qty < order_qty:
                    print(f"[{_now()}] {stk_cd} 지정가 매수 재시도 수량 조정 / 기존 {order_qty}주 -> {safe_qty}주 / 주문가능금액 {format(cur_entr, ',')}원")
                    order_qty = safe_qty
        except Exception as exc:
            print(f"[{_now()}] {stk_cd} 지정가 재시도 전 주문가능금액 조회 실패: {exc}")

        time.sleep(LIMIT_BUY_RETRY_SLEEP_SEC)

    raise RuntimeError(f"{stk_cd} 지정가 매수 주문 실패: 유효한 주문번호를 받지 못했습니다. 마지막응답={last_response}")


def _extract_order_no(order_response: Any) -> Any:
    if isinstance(order_response, dict):
        return order_response.get("ord_no") or order_response.get("order_no") or order_response.get("ordNo")
    return order_response


def _place_buy_market_with_retry(client: KiwoomClient, stk_cd: str, qty: int) -> tuple[str, int]:
    """시장가 매수 주문번호를 받을 때까지 제한적으로 재시도합니다.

    주문번호가 비정상일 때는 주문가능금액/현재가를 다시 확인하고, 그래도 동일하면
    주문 수량을 단계적으로 줄여 재시도합니다. place_buy_market()이 오류 원문을
    숨기는 경우에는 client._post()를 직접 사용하여 응답 원문을 로그에 남깁니다.
    """
    last_response: Any = None
    order_qty = int(qty)

    for attempt in range(1, MARKET_BUY_RETRY_COUNT + 2):
        if order_qty <= 0:
            raise RuntimeError(f"{stk_cd} 시장가 매수 가능 수량이 0주입니다.")

        try:
            response = _place_buy_market_raw(client, stk_cd=stk_cd, qty=order_qty)
            last_response = response
            ord_no = _extract_order_no(response)

            if _is_valid_order_no(ord_no):
                if attempt > 1:
                    print(f"[{_now()}] {stk_cd} 시장가 매수 재시도 성공 / {attempt}회차 / 주문수량 {order_qty}주 / 주문번호 {ord_no}")
                return str(ord_no).strip(), order_qty

            print(f"[{_now()}] {stk_cd} 시장가 매수 주문번호 비정상 / {attempt}회차 / 주문수량 {order_qty}주 / 응답={response}")

        except Exception as exc:
            last_response = exc
            print(f"[{_now()}] {stk_cd} 시장가 매수 주문 예외 / {attempt}회차 / 주문수량 {order_qty}주 / {exc}")

        if attempt > MARKET_BUY_RETRY_COUNT:
            break

        next_qty = order_qty

        # 재시도 전 주문가능금액/현재가 기준으로 수량을 보수적으로 재계산합니다.
        try:
            cur_entr = _safe_int(client.get_current_entr(), 0)
            last_price = _safe_int(client.get_last_price(stk_cd), 0)
            if cur_entr > 0 and last_price > 0:
                safe_qty = int((cur_entr * MARKET_BUY_CASH_SAFETY_RATE) // last_price)
                if 0 < safe_qty < next_qty:
                    next_qty = safe_qty
        except Exception as exc:
            print(f"[{_now()}] {stk_cd} 재시도 전 주문가능금액/현재가 조회 실패: {exc}")

        # 주문번호가 계속 비정상이면 시장가 여유 부족 가능성을 보고 수량을 추가로 줄입니다.
        reduced_qty = max(MARKET_BUY_INVALID_REDUCE_MIN_QTY, int(next_qty * MARKET_BUY_INVALID_REDUCE_RATE))
        if reduced_qty >= next_qty and next_qty > 1:
            reduced_qty = next_qty - 1
        if 0 < reduced_qty < order_qty:
            print(f"[{_now()}] {stk_cd} 시장가 매수 재시도 수량 조정 / 기존 {order_qty}주 -> {reduced_qty}주")
            order_qty = reduced_qty
        elif 0 < next_qty < order_qty:
            print(f"[{_now()}] {stk_cd} 시장가 매수 재시도 수량 조정 / 기존 {order_qty}주 -> {next_qty}주")
            order_qty = next_qty

        time.sleep(MARKET_BUY_RETRY_SLEEP_SEC)

    raise RuntimeError(f"{stk_cd} 시장가 매수 주문 실패: 유효한 주문번호를 받지 못했습니다. 마지막응답={last_response}")


def _place_buy_then_takeprofit(client: KiwoomClient, stk_cd: str, buy_price: int, qty: int) -> dict[str, Any]:
    """BUY_ORDER_TYPE 설정에 따라 지정가/시장가 매수 -> 체결 폴링 표시 -> 종목별 익절 지정가 매도 등록."""
    take_profit_pct = _take_profit_pct(stk_cd)

    if TEST_MODE or b_Test:
        buy_ord_no = "TEST_BUY_NOT_SENT"
        print(f"[{_now()}] [TEST] {stk_cd} 실제 매수 주문 생략 / 가상주문번호 {buy_ord_no} / 주문수량 {qty}주")
        start_ts = time.time()
        deadline = start_ts + TEST_FILL_AFTER_SEC
        poll_count = 0
        while time.time() < deadline:
            poll_count += 1
            now_ts = time.time()
            elapsed_sec = int(now_ts - start_ts)
            remain_sec = max(0, int(deadline - now_ts))
            print(
                f"[{_now()}] [TEST] {stk_cd} 가상 체결 대기 중 {poll_count}회차 / "
                f"경과 {elapsed_sec}초 / 주문 {qty}주 / 체결 0주 / 평균가 0원 / "
                f"강제체결까지 {remain_sec}초"
            )
            time.sleep(float_poll)

        try:
            last_price = client.get_last_price(stk_cd)
            buy_avg_price = _safe_int(last_price, buy_price)
        except Exception:
            buy_avg_price = buy_price

        filled_qty = qty
        print(
            f"[{_now()}] [TEST] {stk_cd} 현재가 기준 가상 체결 처리 / "
            f"체결가 {format(buy_avg_price, ',')}원 / 체결수량 {filled_qty}주"
        )

        take_profit_price = _calc_take_profit_price(stk_cd, buy_avg_price)
        tp_result = _place_take_profit_sell(client, stk_cd, filled_qty, take_profit_price)
        take_profit_ord_no = tp_result.get("sell_ord_no")
        print(
            f"[{_now()}] [TEST] {stk_cd} 익절 지정가 가상 등록 완료 / "
            f"주문번호 {take_profit_ord_no} / 수량 {filled_qty}주 / "
            f"가격 {format(take_profit_price, ',')}원(+{take_profit_pct:.1f}%)"
        )

        return {
            "buy_ord_no": buy_ord_no,
            "buy_avg_price": buy_avg_price,
            "buy_qty": filled_qty,
            "take_profit_ord_no": take_profit_ord_no,
            "take_profit_price": take_profit_price,
            "is_fake_filled": True,
        }

    if not hasattr(client, "place_buy_market"):
        raise AttributeError("KiwoomClient에 place_buy_market(stk_cd, qty) 함수가 없습니다.")
    if not hasattr(client, "get_order_fill_summary"):
        raise AttributeError("KiwoomClient에 get_order_fill_summary(ord_no) 함수가 없습니다.")

    order_type = _buy_order_type()
    if order_type == "LIMIT":
        limit_buy_price = _calc_limit_buy_price(stk_cd, buy_price)
        buy_ord_no, actual_order_qty, actual_order_price = _place_buy_limit_with_retry(client, stk_cd, qty, limit_buy_price)
        qty = actual_order_qty
        print(
            f"[{_now()}] {stk_cd} 지정가 매수 주문 접수 / "
            f"주문번호 {buy_ord_no} / 주문수량 {qty}주 / 주문가 {format(actual_order_price, ',')}원"
        )
    else:
        buy_ord_no, actual_order_qty = _place_buy_market_with_retry(client, stk_cd, qty)
        qty = actual_order_qty
        print(f"[{_now()}] {stk_cd} 시장가 매수 주문 접수 / 주문번호 {buy_ord_no} / 주문수량 {qty}주")

    start_ts = time.time()
    deadline = start_ts + float_timeout
    buy_avg_price: int | None = None
    filled_qty: int = 0
    ord_qty: int = qty
    poll_count = 0

    while time.time() < deadline:
        poll_count += 1
        now_ts = time.time()
        remain_sec = max(0, int(deadline - now_ts))
        elapsed_sec = int(now_ts - start_ts)

        try:
            summ = client.get_order_fill_summary(buy_ord_no)
        except Exception as exc:
            print(f"[{_now()}] {stk_cd} 체결 조회 중 오류 / {exc} / 남은시간 {remain_sec}초")
            time.sleep(float_poll)
            continue

        ord_qty = _safe_int(summ.get("ord_qty"), qty)
        filled_qty = _safe_int(summ.get("filled_qty"), 0)
        avg = _safe_int(summ.get("avg_price"), 0)
        buy_avg_price = avg if avg > 0 else None

        print(
            f"[{_now()}] {stk_cd} 체결 대기 중 {poll_count}회차 / "
            f"경과 {elapsed_sec}초 / 주문 {ord_qty}주 / 체결 {filled_qty}주 / "
            f"평균가 {format(buy_avg_price or 0, ',')}원 / 남은시간 {remain_sec}초"
        )

        if ord_qty > 0 and filled_qty >= ord_qty:
            if buy_avg_price is None:
                last_price = client.get_last_price(stk_cd)
                buy_avg_price = _safe_int(last_price, buy_price)
            break

        time.sleep(float_poll)

    if filled_qty <= 0:
        raise TimeoutError(
            f"{stk_cd} 매수 체결을 확인하지 못했습니다. "
            f"주문번호={buy_ord_no}, timeout={int(float_timeout)}초. "
            "매수 실패 또는 체결 미확인으로 판단하여 익절/DCA트리거 등록을 중단합니다."
        )

    if buy_avg_price is None:
        try:
            last_price = client.get_last_price(stk_cd)
            buy_avg_price = _safe_int(last_price, buy_price)
        except Exception:
            buy_avg_price = buy_price
        print(f"[{_now()}] {stk_cd} 평균 체결가를 확인하지 못해 현재가 {format(buy_avg_price, ',')}원을 사용합니다.")

    sellable_qty = _wait_sellable_qty(client, stk_cd, filled_qty)
    if sellable_qty <= 0:
        raise RuntimeError(
            f"{stk_cd} 매수 체결은 확인했지만 매도가능수량이 0주입니다. "
            "익절 지정가 매도와 DCA 감시 등록을 중단합니다."
        )
    if sellable_qty < filled_qty:
        print(f"[{_now()}] {stk_cd} 매도가능수량이 체결수량보다 작아 {sellable_qty}주만 익절/DCA트리거 대상으로 사용합니다.")
        filled_qty = sellable_qty

    take_profit_price = _calc_take_profit_price(stk_cd, buy_avg_price)
    tp_result = _place_take_profit_sell(client, stk_cd, filled_qty, take_profit_price)
    take_profit_ord_no = _require_valid_order_no(tp_result.get("sell_ord_no"), f"{stk_cd} 익절 지정가 매도 주문")
    print(
        f"[{_now()}] {stk_cd} 익절 지정가 매도 등록 / "
        f"주문번호 {take_profit_ord_no} / 수량 {filled_qty}주 / "
        f"가격 {format(take_profit_price, ',')}원(+{take_profit_pct:.1f}%)"
    )

    return {
        "buy_ord_no": buy_ord_no,
        "buy_avg_price": buy_avg_price,
        "buy_qty": filled_qty,
        "take_profit_ord_no": take_profit_ord_no,
        "take_profit_price": take_profit_price,
        "is_fake_filled": False,
    }


def _rebuy_count(item: dict[str, Any]) -> int:
    return int(item.get("rebuy_count", 0) or 0)


def _item_state(item: dict[str, Any]) -> str:
    return str(item.get("state", STATE_NORMAL) or STATE_NORMAL)


def _entry_price(item: dict[str, Any]) -> int:
    return _safe_int(item.get("entry_price"), _safe_int(item.get("buy_avg_price"), 0))


def _strategy_base_price(item: dict[str, Any]) -> int:
    return _safe_int(item.get("strategy_base_price"), _safe_int(item.get("buy_avg_price"), 0))


def _can_rebuy(item: dict[str, Any], reason: str) -> bool:
    cnt = _rebuy_count(item)
    if cnt >= MAX_REBUY_PER_STOCK:
        print(
            f"[{_now()}] [재진입중단] {item.get('stk_nm', '')}[{item.get('stk_cd', '')}] "
            f"{reason} / 재매수 횟수 {cnt}/{MAX_REBUY_PER_STOCK} 도달"
        )
        return False
    return True


def _place_market_rebuy_then_takeprofit(client: KiwoomClient, item: dict[str, Any], reason: str = "재진입") -> dict[str, Any]:
    """익절/DCA트리거 이후 같은 종목을 시장가로 재매수하고 새 익절 지정가 주문을 등록합니다."""
    stk_cd = _norm_code(item["stk_cd"])
    stk_nm = str(item.get("stk_nm", _target_name(stk_cd)))
    prev_qty = int(item.get("qty", 0))

    if prev_qty <= 0:
        raise RuntimeError(f"{stk_nm}[{stk_cd}] 재진입 수량이 0주입니다.")

    if TEST_MODE or b_Test:
        try:
            buy_avg_price = _safe_int(client.get_last_price(stk_cd), _safe_int(item.get("buy_avg_price"), 0))
        except Exception:
            buy_avg_price = _safe_int(item.get("buy_avg_price"), 0)
        filled_qty = prev_qty
        buy_ord_no = "TEST_REBUY_MARKET_NOT_SENT"
        take_profit_price = _calc_take_profit_price(stk_cd, buy_avg_price)
        tp_result = _place_take_profit_sell(client, stk_cd, filled_qty, take_profit_price)
        take_profit_ord_no = tp_result.get("sell_ord_no")
        print(
            f"[{_now()}] [재진입-TEST] {stk_nm}[{stk_cd}] {reason} 시장가 재매수 가정 / "
            f"수량 {filled_qty}주 / 기준가 {format(buy_avg_price, ',')}원 / "
            f"익절 {format(take_profit_price, ',')}원 / 익절주문 {take_profit_ord_no}"
        )
        _log_trade_event(
            event="REBUY",
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            qty=filled_qty,
            price=buy_avg_price,
            base_price=buy_avg_price,
            order_no=buy_ord_no,
            memo=f"{reason} TEST 재매수",
            state=STATE_NORMAL,
            cycle=int(item.get("rebuy_count", 0)) + 1,
            take_profit_price=take_profit_price,
            stop_loss_price=_calc_stop_loss_price(stk_cd, buy_avg_price, 0),
        )
        return {
            "stk_nm": stk_nm,
            "stk_cd": stk_cd,
            "qty": filled_qty,
            "buy_avg_price": buy_avg_price,
            "entry_price": buy_avg_price,
            "strategy_base_price": buy_avg_price,
            "state": STATE_NORMAL,
            "buy_ord_no": buy_ord_no,
            "take_profit_ord_no": take_profit_ord_no,
            "take_profit_price": take_profit_price,
            "stop_loss_pct": _stop_loss_pct(stk_cd),
            "stop_loss_price": _calc_stop_loss_price(stk_cd, buy_avg_price),
            "rebuy_count": int(item.get("rebuy_count", 0)) + 1,
            "dca_step": 0,
            "dca_reserve_total": int(item.get("dca_reserve_total", 0) or 0),
            "dca_used_amount": 0,
        }

    print(
        f"[{_now()}] [재진입 1/4] {stk_nm}[{stk_cd}] {reason} → 시장가 재매수 시작 / "
        f"요청수량 {prev_qty}주 / 재매수횟수 {_rebuy_count(item) + 1}/{MAX_REBUY_PER_STOCK}"
    )
    buy_ord_no, actual_order_qty = _place_buy_market_with_retry(client, stk_cd, prev_qty)
    print(f"[{_now()}] [재진입 1/4] {stk_nm}[{stk_cd}] 시장가 재매수 주문 접수 / 주문번호 {buy_ord_no} / 수량 {actual_order_qty}주")

    start_ts = time.time()
    deadline = start_ts + float_timeout
    buy_avg_price: int | None = None
    filled_qty = 0
    poll_count = 0

    while time.time() < deadline:
        poll_count += 1
        remain_sec = max(0, int(deadline - time.time()))
        try:
            summ = client.get_order_fill_summary(buy_ord_no)
            ord_qty = _safe_int(summ.get("ord_qty"), actual_order_qty)
            filled_qty = _safe_int(summ.get("filled_qty"), 0)
            avg = _safe_int(summ.get("avg_price"), 0)
            buy_avg_price = avg if avg > 0 else None
            print(
                f"[{_now()}] [재진입 2/4] {stk_nm}[{stk_cd}] 체결 대기 {poll_count}회차 / "
                f"주문 {ord_qty}주 / 체결 {filled_qty}주 / 평균가 {format(buy_avg_price or 0, ',')}원 / 남은시간 {remain_sec}초"
            )
            if ord_qty > 0 and filled_qty >= ord_qty:
                if buy_avg_price is None:
                    buy_avg_price = _safe_int(client.get_last_price(stk_cd), 0)
                break
        except Exception as exc:
            print(f"[{_now()}] [재진입 2/4] {stk_nm}[{stk_cd}] 체결 조회 오류: {exc}")
        time.sleep(float_poll)

    if filled_qty <= 0:
        raise TimeoutError(f"{stk_nm}[{stk_cd}] 재진입 매수 체결 확인 실패 / 주문번호 {buy_ord_no}")
    if buy_avg_price is None or buy_avg_price <= 0:
        buy_avg_price = _safe_int(client.get_last_price(stk_cd), _safe_int(item.get("buy_avg_price"), 0))

    sellable_qty = _wait_sellable_qty(client, stk_cd, filled_qty)
    if sellable_qty <= 0:
        raise RuntimeError(f"{stk_nm}[{stk_cd}] 재진입 매수 후 매도가능수량이 0주입니다.")
    if sellable_qty < filled_qty:
        print(f"[{_now()}] [재진입 3/4] {stk_nm}[{stk_cd}] 매도가능수량 기준으로 감시수량 조정 {filled_qty}주 -> {sellable_qty}주")
        filled_qty = sellable_qty

    take_profit_price = _calc_take_profit_price(stk_cd, buy_avg_price)
    tp_result = _place_take_profit_sell(client, stk_cd, filled_qty, take_profit_price)
    take_profit_ord_no = _require_valid_order_no(tp_result.get("sell_ord_no"), f"{stk_cd} 재진입 익절 지정가 매도 주문")
    stop_loss_price = _calc_stop_loss_price(stk_cd, buy_avg_price)
    print(
        f"[{_now()}] [재진입 4/4] {stk_nm}[{stk_cd}] 재진입 완료 / "
        f"매수가 {format(buy_avg_price, ',')}원 / 수량 {filled_qty}주 / "
        f"익절 {format(take_profit_price, ',')}원 / DCA트리거 {format(stop_loss_price, ',')}원 / "
        f"익절주문 {take_profit_ord_no}"
    )
    _log_trade_event(
        event="REBUY",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        qty=filled_qty,
        price=buy_avg_price,
        base_price=buy_avg_price,
        order_no=buy_ord_no,
        memo=reason,
        state=STATE_NORMAL,
        cycle=int(item.get("rebuy_count", 0)) + 1,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
    )

    return {
        "stk_nm": stk_nm,
        "stk_cd": stk_cd,
        "qty": filled_qty,
        "buy_avg_price": buy_avg_price,
        "entry_price": buy_avg_price,
        "strategy_base_price": buy_avg_price,
        "state": STATE_NORMAL,
        "buy_ord_no": buy_ord_no,
        "take_profit_ord_no": take_profit_ord_no,
        "take_profit_price": take_profit_price,
        "stop_loss_pct": _stop_loss_pct(stk_cd),
        "stop_loss_price": stop_loss_price,
        "rebuy_count": int(item.get("rebuy_count", 0)) + 1,
        "dca_step": 0,
        "dca_reserve_total": int(item.get("dca_reserve_total", 0) or 0),
        "dca_used_amount": 0,
    }


def _cancel_take_profit_order(client: KiwoomClient, sell_ord_no: Any, stk_cd: str, qty: int) -> Any:
    """손절 시장가 매도 전, 이미 걸어둔 익절 지정가 주문을 취소합니다."""
    if not sell_ord_no:
        return None

    if str(sell_ord_no).startswith("TEST_"):
        return "TEST_CANCEL_SKIPPED"

    try:
        return _cancel_order_generic(client, ord_no=str(sell_ord_no), stk_cd=stk_cd, qty=qty)
    except Exception as exc:
        print(f"[{_now()}] {stk_cd} 익절 주문번호 직접 취소 실패: {exc}")
        return {"error": str(exc)}




def _cancel_result_looks_ok(result: Any) -> bool:
    text = str(result or "")
    if not text:
        return False
    return any(token in text for token in ("완료", "성공", "접수", "TEST_CANCEL")) and "error" not in text.lower()

def _format_gap_pct(last_price: int, stop_price: int) -> str:
    if stop_price <= 0:
        return "-"
    gap = (last_price - stop_price) / stop_price * 100.0
    sign = "+" if gap >= 0 else ""
    return f"{sign}{gap:.2f}%"


def _format_profit_pct(last_price: int, buy_price: int) -> str:
    if buy_price <= 0:
        return "-"
    pct = (last_price - buy_price) / buy_price * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _format_sellable_display(sellable_qty: int, holding_qty: int, take_profit_ord_no: Any = None) -> str:
    if sellable_qty > 0:
        return f"{sellable_qty}주"
    if holding_qty > 0 and take_profit_ord_no:
        return "0주(익절예약 묶임)"
    return f"{sellable_qty}주"



def _format_target_gap_pct(last_price: int, target_price: int) -> str:
    """현재가에서 목표가까지 남은 퍼센트. 익절은 +, DCA 트리거는 - 방향으로 표시합니다."""
    if last_price <= 0 or target_price <= 0:
        return "-"
    pct = (target_price - last_price) / last_price * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def _format_dca_trigger_gap_pct(last_price: int, trigger_price: int) -> str:
    """현재가에서 DCA 트리거 가격까지 하락 여유를 -%로 표시합니다."""
    if last_price <= 0 or trigger_price <= 0:
        return "-"
    pct = (trigger_price - last_price) / last_price * 100.0
    return f"{pct:.2f}%"


def _format_watch_line(item: dict[str, Any], stk_cd: str, last_price: int, holding_qty: int, sellable_qty: int, extra: str = "") -> str:
    tp_price = _safe_int(item.get("take_profit_price"), 0)
    trigger_price = _safe_int(item.get("stop_loss_price"), 0)
    dca_used = int(item.get("dca_used_amount", 0) or 0)
    dca_total = int(item.get("dca_reserve_total", 0) or 0)
    sellable_text = _format_sellable_display(sellable_qty, holding_qty, item.get("take_profit_ord_no"))
    parts = [
        f"[{_now()}] [감시] {item['stk_nm']}[{stk_cd}]",
        f"상태 {_item_state(item)}",
        f"현재 {format(last_price, ',')}원",
        f"평단 {format(_strategy_base_price(item), ',')}원({_format_profit_pct(last_price, _strategy_base_price(item))})",
        f"최초 {_format_profit_pct(last_price, _entry_price(item))}",
        f"익절 {format(tp_price, ',')}원({_format_target_gap_pct(last_price, tp_price)})",
        f"DCA {format(trigger_price, ',')}원({_format_dca_trigger_gap_pct(last_price, trigger_price)})",
        f"보유 {holding_qty}주",
        f"매도가능 {sellable_text}",
        f"DCA {int(item.get('dca_step', _rebuy_count(item)) or 0)}/{len(DCA_BUDGET_WEIGHTS)}",
    ]
    if dca_total > 0:
        parts.append(f"DCA예산 {format(dca_used, ',')}/{format(dca_total, ',')}원")
    if item.get("take_profit_ord_no"):
        parts.append(f"익절주문 {item.get('take_profit_ord_no')}")
    if extra:
        parts.append(extra)
    return " | ".join(parts)


def _dca_weight_sum() -> float:
    total = sum(float(x) for x in DCA_BUDGET_WEIGHTS if float(x) > 0)
    return total if total > 0 else 1.0


def _dca_step_budget(item: dict[str, Any], step_index: int) -> int:
    """step_index는 0부터 시작합니다."""
    reserve_total = int(item.get("dca_reserve_total", 0) or 0)
    used = int(item.get("dca_used_amount", 0) or 0)
    if reserve_total <= 0:
        return 0
    if step_index < 0:
        step_index = 0
    if step_index >= len(DCA_BUDGET_WEIGHTS):
        return 0
    weight = float(DCA_BUDGET_WEIGHTS[step_index])
    budget = int(reserve_total * weight / _dca_weight_sum())
    remaining = max(0, reserve_total - used)
    return min(budget, remaining)


def _calc_weighted_avg_price(old_qty: int, old_avg: int, add_qty: int, add_price: int) -> int:
    total_qty = int(old_qty or 0) + int(add_qty or 0)
    if total_qty <= 0:
        return int(add_price or old_avg or 0)
    amount = int(old_qty or 0) * int(old_avg or 0) + int(add_qty or 0) * int(add_price or 0)
    return int(round(amount / total_qty))


def _place_dca_buy(client: KiwoomClient, stk_cd: str, stk_nm: str, budget: int, ref_price: int) -> tuple[str, int, int, int]:
    """DCA 추가매수. 반환: 주문번호, 체결수량, 평균체결가, 주문금액추정"""
    if budget <= 0:
        raise RuntimeError(f"{stk_nm}[{stk_cd}] DCA 예산이 없습니다.")

    if TEST_MODE:
        order_price = int(ref_price)
        qty = int(budget // order_price) if order_price > 0 else 0
        if qty <= 0:
            raise RuntimeError(f"{stk_nm}[{stk_cd}] TEST DCA 가능수량 0주 / 예산 {budget} / 기준가 {ref_price}")
        ord_no = "TEST_DCA_BUY_NOT_SENT"
        print(f"[{_now()}] [DCA-TEST] {stk_nm}[{stk_cd}] 추가매수 가정 / 예산 {format(budget, ',')}원 / 수량 {qty}주 / 체결가 {format(order_price, ',')}원")
        return ord_no, qty, order_price, qty * order_price

    order_type = _buy_order_type() if DCA_BUY_USES_BUY_ORDER_TYPE else "LIMIT"
    if order_type == "LIMIT":
        order_price = _calc_limit_buy_price(stk_cd, ref_price)
        qty = int(budget // order_price) if order_price > 0 else 0
        if qty <= 0:
            raise RuntimeError(f"{stk_nm}[{stk_cd}] DCA 지정가 가능수량 0주 / 예산 {budget} / 주문가 {order_price}")
        buy_ord_no, actual_qty, actual_order_price = _place_buy_limit_with_retry(client, stk_cd, qty, order_price)
        print(f"[{_now()}] [DCA 2/5] {stk_nm}[{stk_cd}] 지정가 추가매수 주문 / 주문번호 {buy_ord_no} / 수량 {actual_qty}주 / 주문가 {format(actual_order_price, ',')}원")
    else:
        order_price = ref_price
        safe_budget = int(budget * MARKET_BUY_CASH_SAFETY_RATE)
        qty = int(safe_budget // order_price) if order_price > 0 else 0
        if qty <= 0:
            raise RuntimeError(f"{stk_nm}[{stk_cd}] DCA 시장가 가능수량 0주 / 예산 {budget} / 안전예산 {safe_budget} / 현재가 {order_price}")
        buy_ord_no, actual_qty = _place_buy_market_with_retry(client, stk_cd, qty)
        print(f"[{_now()}] [DCA 2/5] {stk_nm}[{stk_cd}] 시장가 추가매수 주문 / 주문번호 {buy_ord_no} / 수량 {actual_qty}주")

    start_ts = time.time()
    deadline = start_ts + float_timeout
    filled_qty = 0
    avg_price = 0
    poll_count = 0
    while time.time() < deadline:
        poll_count += 1
        remain_sec = max(0, int(deadline - time.time()))
        try:
            summ = client.get_order_fill_summary(buy_ord_no)
            ord_qty = _safe_int(summ.get("ord_qty"), actual_qty)
            filled_qty = _safe_int(summ.get("filled_qty"), 0)
            avg_price = _safe_int(summ.get("avg_price"), 0)
            print(
                f"[{_now()}] [DCA 3/5] {stk_nm}[{stk_cd}] 체결 대기 {poll_count}회차 / "
                f"주문 {ord_qty}주 / 체결 {filled_qty}주 / 평균가 {format(avg_price, ',')}원 / 남은시간 {remain_sec}초"
            )
            if ord_qty > 0 and filled_qty >= ord_qty:
                if avg_price <= 0:
                    avg_price = _safe_int(client.get_last_price(stk_cd), ref_price)
                break
        except Exception as exc:
            print(f"[{_now()}] [DCA 3/5] {stk_nm}[{stk_cd}] 체결 조회 오류: {exc}")
        time.sleep(float_poll)

    if filled_qty <= 0:
        raise TimeoutError(f"{stk_nm}[{stk_cd}] DCA 추가매수 체결 확인 실패 / 주문번호 {buy_ord_no}")
    if avg_price <= 0:
        avg_price = _safe_int(client.get_last_price(stk_cd), ref_price)
    return buy_ord_no, filled_qty, avg_price, filled_qty * avg_price

def _reset_prices_after_stop_touch(
    client: KiwoomClient,
    item: dict[str, Any],
    last_price: int,
    holding_qty: int,
    sellable_qty: int,
) -> bool:
    """DCA트리거선 터치 시 매도하지 않고 DCA 추가매수 후 평균단가 기준 익절/DCA트리거 주문을 재설정합니다."""
    stk_cd = _norm_code(item["stk_cd"])
    stk_nm = str(item.get("stk_nm", _target_name(stk_cd)))
    current_count = _rebuy_count(item)
    next_count = current_count + 1

    old_stop_price = _safe_int(item.get("stop_loss_price"), 0)
    old_tp_price = _safe_int(item.get("take_profit_price"), 0)
    old_tp_ord_no = item.get("take_profit_ord_no")
    entry_price = _entry_price(item)
    old_avg_price = _strategy_base_price(item)
    if old_avg_price <= 0:
        old_avg_price = _safe_int(item.get("buy_avg_price"), last_price)

    if next_count > MAX_REBUY_PER_STOCK:
        return False
    if DCA_ON_STOP_TOUCH_ENABLED and current_count >= len(DCA_BUDGET_WEIGHTS):
        return False

    dca_budget = _dca_step_budget(item, current_count)

    print(
        f"[{_now()}] [DCA] {stk_nm}[{stk_cd}] DCA트리거선 터치 / "
        f"현재 {format(last_price, ',')}원 <= 기존DCA트리거 {format(old_stop_price, ',')}원 / "
        f"최초매입대비 {_format_profit_pct(last_price, entry_price)} / "
        f"DCA단계 {next_count}/{MAX_REBUY_PER_STOCK} / 단계예산 {format(dca_budget, ',')}원"
    )

    if dca_budget <= 0:
        print(f"[{_now()}] [DCA중단] {stk_nm}[{stk_cd}] 남은 DCA 예산이 없어 최종 DCA트리거 대상으로 전환합니다.")
        return False

    print(
        f"[{_now()}] [DCA 1/5] {stk_nm}[{stk_cd}] 기존 익절 주문 취소 / "
        f"주문번호 {old_tp_ord_no} / 기존익절 {format(old_tp_price, ',')}원"
    )
    cancel_result = _cancel_take_profit_order(client, old_tp_ord_no, stk_cd, holding_qty)
    print(f"[{_now()}] [DCA 1/5] {stk_nm}[{stk_cd}] 취소 결과: {cancel_result}")
    if not TEST_MODE:
        time.sleep(ORDER_CANCEL_WAIT_SEC)

    try:
        buy_ord_no, add_qty, add_avg_price, add_amount = _place_dca_buy(
            client=client,
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            budget=dca_budget,
            ref_price=last_price,
        )
    except Exception as exc:
        print(f"[{_now()}] [DCA실패] {stk_nm}[{stk_cd}] 추가매수 실패: {exc}")
        # 기존 익절을 취소한 상태일 수 있으므로, 가능한 경우 기존 수량으로 익절을 다시 걸어둡니다.
        try:
            if holding_qty > 0 and old_tp_price > 0:
                print(f"[{_now()}] [DCA복구] {stk_nm}[{stk_cd}] 기존 평균단가 기준 익절 주문 복구 시도 / 수량 {holding_qty}주 / 가격 {format(old_tp_price, ',')}원")
                tp_restore = _place_take_profit_sell(client, stk_cd, holding_qty, old_tp_price)
                item["take_profit_ord_no"] = tp_restore.get("sell_ord_no")
                item["take_profit_price"] = old_tp_price
        except Exception as restore_exc:
            print(f"[{_now()}] [DCA복구실패] {stk_nm}[{stk_cd}] 익절 복구 실패: {restore_exc}")
        return False

    old_qty = int(holding_qty or item.get("qty", 0) or 0)
    new_qty = old_qty + add_qty
    new_avg_price = _calc_weighted_avg_price(old_qty, old_avg_price, add_qty, add_avg_price)

    # DCA 후 익절은 평균단가 기준 고정 익절률로 다시 계산합니다.
    new_tp_pct = _take_profit_pct(stk_cd)
    new_tp_price = _calc_take_profit_price_with_pct(new_avg_price, new_tp_pct)
    new_stop_pct = _stop_loss_pct_by_cycle(stk_cd, next_count)
    new_stop_price = _calc_stop_loss_price(stk_cd, new_avg_price, next_count)

    print(
        f"[{_now()}] [DCA 4/5] {stk_nm}[{stk_cd}] 평균단가 재계산 / "
        f"기존 {old_qty}주@{format(old_avg_price, ',')}원 + "
        f"추가 {add_qty}주@{format(add_avg_price, ',')}원 -> "
        f"새수량 {new_qty}주 / 새평균 {format(new_avg_price, ',')}원"
    )

    if not TEST_MODE:
        # 체결/잔고 반영 확인. 실패해도 계산 수량으로 익절 등록을 시도합니다.
        try:
            sellable = _wait_sellable_qty(client, stk_cd, new_qty, timeout_sec=10.0, poll_sec=1.0)
            if sellable > 0:
                new_qty = min(new_qty, sellable)
        except Exception as exc:
            print(f"[{_now()}] [DCA 4/5] {stk_nm}[{stk_cd}] 매도가능수량 확인 실패: {exc}")

    print(
        f"[{_now()}] [DCA 5/5] {stk_nm}[{stk_cd}] 새 익절 주문 등록 / "
        f"평균단가 {format(new_avg_price, ',')}원 / 익절률 {new_tp_pct:.2f}% / "
        f"새익절 {format(new_tp_price, ',')}원 / 새DCA트리거 {format(new_stop_price, ',')}원 / 수량 {new_qty}주"
    )
    try:
        tp_result = _place_take_profit_sell(client, stk_cd, new_qty, new_tp_price)
        new_tp_ord_no = _require_valid_order_no(tp_result.get("sell_ord_no"), f"{stk_cd} DCA 익절 지정가 매도 주문")
    except Exception as exc:
        print(f"[{_now()}] [DCA실패] {stk_nm}[{stk_cd}] 새 익절 주문 등록 실패: {exc}. 감시는 유지하지만 익절주문번호는 비웁니다.")
        new_tp_ord_no = None

    item["state"] = STATE_RECOVERY
    item["rebuy_count"] = next_count
    item["dca_step"] = next_count
    item["dca_used_amount"] = int(item.get("dca_used_amount", 0) or 0) + int(add_amount or 0)
    item["strategy_base_price"] = new_avg_price
    item["buy_avg_price"] = new_avg_price
    item["entry_price"] = entry_price
    item["take_profit_pct"] = new_tp_pct
    item["take_profit_price"] = new_tp_price
    item["take_profit_ord_no"] = new_tp_ord_no
    item["stop_loss_pct"] = new_stop_pct
    item["stop_loss_price"] = new_stop_price
    item["qty"] = new_qty

    _log_trade_event(
        event="DCA_BUY_RESET",
        stk_cd=stk_cd,
        stk_nm=stk_nm,
        qty=add_qty,
        price=add_avg_price,
        base_price=new_avg_price,
        order_no=buy_ord_no,
        memo="DCA트리거선 터치: DCA 추가매수 후 평균단가 기준 익절 재등록",
        state=item["state"],
        cycle=next_count,
        take_profit_price=new_tp_price,
        stop_loss_price=new_stop_price,
        dca_budget=dca_budget,
        dca_used_amount=item["dca_used_amount"],
        total_qty=new_qty,
        avg_price=new_avg_price,
    )

    print(
        f"[{_now()}] [DCA완료] {stk_nm}[{stk_cd}] "
        f"상태 {item['state']} / 최초매입 {format(entry_price, ',')}원 / "
        f"새평균 {format(new_avg_price, ',')}원 / 보유 {new_qty}주 / "
        f"새익절 {format(new_tp_price, ',')}원(+{new_tp_pct:.2f}%) / "
        f"새DCA트리거 {format(new_stop_price, ',')}원(-{new_stop_pct:.2f}%) / "
        f"DCA사용 {format(item['dca_used_amount'], ',')}원/{format(int(item.get('dca_reserve_total', 0) or 0), ',')}원 / "
        f"익절주문 {new_tp_ord_no}"
    )
    return True


def _place_stop_loss_market_sell(client: KiwoomClient, item: dict[str, Any], sellable_qty: int) -> dict[str, Any]:
    """DCA트리거가 도달 종목만 익절 주문 취소 후 시장가 매도합니다."""
    stk_cd = _norm_code(item["stk_cd"])
    stk_nm = str(item.get("stk_nm", stk_cd))
    watch_qty = int(item.get("qty", 0))
    qty = watch_qty if watch_qty > 0 else int(sellable_qty)
    take_profit_ord_no = item.get("take_profit_ord_no")

    if qty <= 0:
        return {"sell_ord_no": None, "reason": "qty <= 0"}

    print(f"[{_now()}] [DCA트리거 1/3] {stk_nm}[{stk_cd}] 익절 미체결 주문 취소 시도 / 주문번호 {take_profit_ord_no}")
    cancel_result = _cancel_take_profit_order(client, take_profit_ord_no, stk_cd, qty)
    print(f"[{_now()}] [DCA트리거 1/3] {stk_nm}[{stk_cd}] 익절 주문 취소 결과: {cancel_result}")

    extra_cancel_results = []
    # 주문번호 직접 취소가 실패했거나 주문번호가 없는 복구 상황에서만 미체결 조회를 추가 시도합니다.
    if not TEST_MODE and not _cancel_result_looks_ok(cancel_result):
        print(f"[{_now()}] [DCA트리거 보완] {stk_nm}[{stk_cd}] 직접 취소 확인이 불명확하여 동일종목 미체결 매도 주문을 추가 확인합니다.")
        extra_cancel_results = _cancel_before_sell_by_codes(
            client,
            target_codes={stk_cd},
            reason=f"{stk_cd} DCA트리거 전 동일종목 미체결 매도 취소",
        )

    time.sleep(max(1.0, ORDER_CANCEL_WAIT_SEC))

    if TEST_MODE:
        refreshed_sellable_qty = _test_sellable_qty(stk_cd, qty)
    else:
        balance_map = _get_balance_map(client, force_refresh=True)
        refreshed_sellable_qty = _sellable_qty_from_balance_map(balance_map, stk_cd)

    qty = min(qty, refreshed_sellable_qty)
    print(f"[{_now()}] [DCA트리거 2/3] {stk_nm}[{stk_cd}] 취소 후 매도가능수량 확인 / 매도가능 {refreshed_sellable_qty}주 / 실행수량 {qty}주")

    if qty <= 0:
        return {
            "cancel_result": cancel_result,
            "extra_cancel_results": extra_cancel_results,
            "sell_ord_no": None,
            "reason": "sellable_qty became 0 after cancel",
        }

    if TEST_MODE:
        sell_ord_no = "TEST_STOP_LOSS_MARKET_NOT_SENT"
        print(f"[{_now()}] [DCA트리거 3/3] [TEST] {stk_nm}[{stk_cd}] 시장가 매도 생략 / 가상주문번호 {sell_ord_no} / 수량 {qty}주")
        return {"cancel_result": cancel_result, "extra_cancel_results": extra_cancel_results, "sell_ord_no": sell_ord_no, "qty": qty, "method": "test_place_sell_market_skipped"}

    if hasattr(client, "place_sell_market"):
        sell_ord_no = client.place_sell_market(stk_cd, qty)
        print(f"[{_now()}] [DCA트리거 3/3] {stk_nm}[{stk_cd}] 시장가 매도 접수 / 주문번호 {sell_ord_no} / 수량 {qty}주")
        return {"cancel_result": cancel_result, "extra_cancel_results": extra_cancel_results, "sell_ord_no": sell_ord_no, "qty": qty, "method": "place_sell_market"}

    if hasattr(client, "place_loss_cut_sell"):
        loss_result = client.place_loss_cut_sell(buy_ord_no=str(take_profit_ord_no or item.get("buy_ord_no")), stk_cd=stk_cd, qty=qty)
        return {"cancel_result": cancel_result, "extra_cancel_results": extra_cancel_results, "loss_result": loss_result, "qty": qty, "method": "place_loss_cut_sell_fallback"}

    raise AttributeError("KiwoomClient에 place_sell_market(stk_cd, qty) 함수가 없습니다.")


# ===============================
# DCA 감시
# ===============================

def _watch_stop_loss(client: KiwoomClient, watch_items: list[dict[str, Any]]) -> None:
    if not watch_items:
        print(f"[{_now()}] DCA 감시 대상이 없습니다.")
        return

    if not hasattr(client, "place_sell_market") and not hasattr(client, "place_loss_cut_sell"):
        print(f"[{_now()}] KiwoomClient에 손절 매도 함수가 없어 DCA 감시를 시작하지 않습니다.")
        return

    # 감시 항목을 상태 머신 필드로 정규화합니다.
    for item in watch_items:
        if "entry_price" not in item:
            item["entry_price"] = _safe_int(item.get("buy_avg_price"), 0)
        if "strategy_base_price" not in item:
            item["strategy_base_price"] = _safe_int(item.get("buy_avg_price"), 0)
        if "state" not in item:
            item["state"] = STATE_NORMAL
        if "take_profit_pct" not in item:
            item["take_profit_pct"] = _take_profit_pct_by_cycle(_norm_code(item.get("stk_cd", "")), _rebuy_count(item))
        # 과거 버전/복구 경로에서 익절 주문번호는 있으나 익절가가 0으로 들어오는 경우가 있어 표시와 판단을 보정합니다.
        if _safe_int(item.get("take_profit_price"), 0) <= 0:
            base_for_tp = _strategy_base_price(item) or _safe_int(item.get("buy_avg_price"), 0)
            if base_for_tp > 0:
                item["take_profit_price"] = _calc_take_profit_price_with_pct(base_for_tp, float(item.get("take_profit_pct") or _take_profit_pct(_norm_code(item.get("stk_cd", "")))))
    active = {_norm_code(item["stk_cd"]): item for item in watch_items if int(item.get("qty", 0)) > 0}
    last_print_time = 0.0
    virtual_prices: dict[str, int] = {}

    print("\n" + "=" * 72)
    print(f"[{_now()}] 종목별 DCA 감시 시작")
    print("=" * 72)
    for item in active.values():
        stk_cd = _norm_code(item["stk_cd"])
        print(
            f"{item['stk_nm']}[{stk_cd}] "
            f"상태 {_item_state(item)} / 감시수량 {item['qty']}주 / "
            f"최초매입 {format(_entry_price(item), ',')}원 / 기준가 {format(_strategy_base_price(item), ',')}원 / "
            f"익절 {format(_safe_int(item.get('take_profit_price')), ',')}원 / DCA트리거 {format(item['stop_loss_price'], ',')}원 / "
            f"회차 {_rebuy_count(item)}/{MAX_REBUY_PER_STOCK} / 익절주문번호 {item.get('take_profit_ord_no')}"
        )

    if TEST_MODE:
        print("[TEST] DCA 감시 현재가는 API 가격이 아니라 종목별 가상 가격을 사용합니다.")
        for item in active.values():
            stk_cd = _norm_code(item["stk_cd"])
            print(f"[TEST] {item['stk_nm']}[{stk_cd}] 1초마다 -{_test_down_rate(stk_cd) * 100:.1f}%")

    print("Ctrl+C를 누르면 DCA 감시를 중단합니다.")

    try:
        while active:
            if _force_exit_time_reached():
                _print_force_exit_header()
                print(f"[{_now()}] DCA 감시를 중단하고 전체 청산을 실행합니다.")
                _run_sell_all_mode(client, auto_yes=True)
                return

            remove_codes: list[str] = []
            now_ts = time.time()
            should_print = (now_ts - last_print_time) >= STOP_LOSS_PRINT_SEC

            balance_map = {} if TEST_MODE else _get_balance_map(client)
            if not TEST_MODE and not balance_map:
                if should_print:
                    print(f"[{_now()}] 잔고 조회 결과가 비어 있어 이번 DCA 감시 회차는 건너뜁니다. 감시 대상은 유지합니다.")
                    last_print_time = now_ts
                time.sleep(STOP_LOSS_CHECK_SEC)
                continue

            for stk_cd, item in list(active.items()):
                stop_price = int(item["stop_loss_price"])

                # 익절 지정가 주문이 걸려 있으면 매도가능수량은 0이 될 수 있습니다.
                # 따라서 감시 제외 여부는 매도가능수량이 아니라 보유수량 기준으로 판단합니다.
                if TEST_MODE:
                    holding_qty = int(item.get("qty", 0))
                    sellable_qty = _test_sellable_qty(stk_cd, holding_qty)
                else:
                    holding_qty = _holding_qty_from_balance_map(balance_map, stk_cd)
                    sellable_qty = _sellable_qty_from_balance_map(balance_map, stk_cd)

                item["holding_qty"] = holding_qty
                item["sellable_qty"] = sellable_qty

                if holding_qty <= 0:
                    # 익절 지정가가 체결되어 보유수량이 0주가 된 경우, 마감 전에는 같은 종목을 다시 매수합니다.
                    if TAKE_PROFIT_REBUY_ENABLED and not _force_exit_time_reached() and _can_rebuy(item, "익절 후 재진입 제한"):
                        tp_price_est = _safe_int(item.get("take_profit_price"), 0)
                        base_price_est = _strategy_base_price(item)
                        qty_est = int(item.get("qty", 0) or 0)
                        profit_est = (tp_price_est - base_price_est) * qty_est if tp_price_est and base_price_est and qty_est else None
                        profit_pct_est = ((tp_price_est - base_price_est) / base_price_est * 100.0) if tp_price_est and base_price_est else None
                        _log_trade_event(
                            event="TAKE_PROFIT_FILLED",
                            stk_cd=stk_cd,
                            stk_nm=item["stk_nm"],
                            qty=qty_est,
                            price=tp_price_est,
                            base_price=base_price_est,
                            order_no=item.get("take_profit_ord_no"),
                            profit_amount=profit_est,
                            profit_pct=profit_pct_est,
                            memo="보유수량 0주: 익절 체결로 추정",
                            state=_item_state(item),
                            cycle=_rebuy_count(item),
                            take_profit_price=tp_price_est,
                            stop_loss_price=item.get("stop_loss_price"),
                        )
                        print(
                            f"[{_now()}] [익절체결] {item['stk_nm']}[{stk_cd}] 보유수량 0주 확인 / "
                            f"익절 체결로 판단하고 시장가 재진입을 시도합니다. "
                            f"재매수횟수 {_rebuy_count(item)}/{MAX_REBUY_PER_STOCK}"
                        )
                        try:
                            new_item = _place_market_rebuy_then_takeprofit(client, item, reason="익절 후 재진입")
                            active[stk_cd] = new_item
                            item = new_item
                            # TEST 가상 가격은 새 매입가 기준으로 다시 시작합니다.
                            virtual_prices.pop(stk_cd, None)
                            continue
                        except Exception as exc:
                            print(
                                f"[{_now()}] [재진입실패] {item['stk_nm']}[{stk_cd}] 재매수/익절 재등록 실패: {exc}. "
                                "해당 종목은 감시에서 제외합니다."
                            )
                            remove_codes.append(stk_cd)
                            continue

                    print(
                        f"[{_now()}] {item['stk_nm']}[{stk_cd}] 보유수량이 0주입니다. "
                        "익절 체결 또는 보유수량 없음으로 판단하여 DCA 감시에서 제외합니다."
                    )
                    remove_codes.append(stk_cd)
                    continue

                if TEST_MODE:
                    rate = _test_down_rate(stk_cd)
                    if stk_cd not in virtual_prices:
                        base_price = _safe_int(item.get("buy_avg_price"), 0)
                        if base_price <= 0:
                            try:
                                base_price = int(client.get_last_price(stk_cd))
                            except Exception as exc:
                                print(f"[{_now()}] {item['stk_nm']}[{stk_cd}] TEST 기준가 조회 실패: {exc}")
                                continue
                        virtual_prices[stk_cd] = base_price
                    else:
                        virtual_prices[stk_cd] = int(virtual_prices[stk_cd] * (1 - rate))
                    last_price = int(virtual_prices[stk_cd])

                    if should_print:
                        print(_format_watch_line(item, stk_cd, last_price, holding_qty, sellable_qty, extra=f"TEST -{rate * 100:.1f}%"))
                else:
                    try:
                        last_price = int(client.get_last_price(stk_cd))
                    except Exception as exc:
                        print(f"[{_now()}] {item['stk_nm']}[{stk_cd}] 현재가 조회 실패: {exc}")
                        continue

                    if should_print:
                        print(_format_watch_line(item, stk_cd, last_price, holding_qty, sellable_qty))

                if last_price <= stop_price:
                    current_count = _rebuy_count(item)
                    next_count = current_count + 1

                    # DCA트리거가에 닿아도 즉시 매도하지 않고 현재가 기준으로 익절/DCA트리거을 다시 설정합니다.
                    # 단, MAX_REBUY_PER_STOCK에 도달하면 실제 손절 시장가 매도를 실행합니다.
                    if STOP_LOSS_PRICE_RESET_ENABLED and next_count < MAX_REBUY_PER_STOCK and not _force_exit_time_reached():
                        reset_ok = _reset_prices_after_stop_touch(
                            client=client,
                            item=item,
                            last_price=last_price,
                            holding_qty=holding_qty,
                            sellable_qty=sellable_qty,
                        )
                        active[stk_cd] = item
                        if TEST_MODE:
                            virtual_prices[stk_cd] = last_price
                        if reset_ok:
                            continue

                    print(
                        f"[{_now()}] [최종손절] {item['stk_nm']}[{stk_cd}] "
                        f"현재 {format(last_price, ',')}원 <= DCA트리거 {format(stop_price, ',')}원 / "
                        f"회차 {current_count}/{MAX_REBUY_PER_STOCK} / 감시수량 {item['qty']}주 / 상태 {STATE_EXIT}"
                    )
                    qty_est = int(item.get("qty", 0) or 0)
                    base_price_est = _strategy_base_price(item)
                    profit_est = (last_price - base_price_est) * qty_est if last_price and base_price_est and qty_est else None
                    profit_pct_est = ((last_price - base_price_est) / base_price_est * 100.0) if last_price and base_price_est else None
                    loss_result = _place_stop_loss_market_sell(client, item, sellable_qty)
                    _log_trade_event(
                        event="FINAL_STOP_SELL",
                        stk_cd=stk_cd,
                        stk_nm=item["stk_nm"],
                        qty=int(loss_result.get("qty", qty_est) or qty_est),
                        price=last_price,
                        base_price=base_price_est,
                        order_no=loss_result.get("sell_ord_no"),
                        profit_amount=profit_est,
                        profit_pct=profit_pct_est,
                        memo="최대 회차 도달 또는 재설정 실패로 최종 DCA트리거",
                        state=STATE_EXIT,
                        cycle=current_count,
                        take_profit_price=item.get("take_profit_price"),
                        stop_loss_price=stop_price,
                    )
                    print(
                        f"[{_now()}] [최종손절완료] {item['stk_nm']}[{stk_cd}] "
                        f"매도주문번호 {loss_result.get('sell_ord_no')} / "
                        f"매도수량 {loss_result.get('qty', 0)}주 / "
                        f"방식 {loss_result.get('method', loss_result.get('reason', '-'))}"
                    )

                    remove_codes.append(stk_cd)


            if should_print:
                last_print_time = now_ts

            for stk_cd in remove_codes:
                active.pop(stk_cd, None)

            if active:
                time.sleep(STOP_LOSS_CHECK_SEC)

        print(f"[{_now()}] 모든 DCA 감시 대상이 종료되었습니다.")

    except KeyboardInterrupt:
        print(f"\n[{_now()}] 사용자 중단(Ctrl+C). DCA 감시를 종료합니다.")


# ===============================
# 재시작/복구 모드
# ===============================

def _build_restore_items_from_config_and_args(args: argparse.Namespace) -> tuple[list[dict[str, Any]], bool]:
    cli_values = list(args.restore or []) + list(args.restart or [])
    if cli_values:
        return _parse_restore_args(cli_values), bool(args.yes)

    if RESTORE_MODE:
        items: list[dict[str, Any]] = []
        for raw in RESTORE_STOCKS:
            code = _norm_code(raw.get("code"))
            buy_price = _safe_int(raw.get("buy_price"))
            if code and buy_price > 0:
                items.append({"code": code, "buy_price": buy_price})
        return items, bool(RESTORE_AUTO_YES)

    return [], False


def _run_restore_mode(client: KiwoomClient, restore_items: list[dict[str, Any]], auto_yes: bool = False) -> None:
    print("\n" + "=" * 72)
    print(f"[{_now()}] 재시작/복구 모드")
    print("=" * 72)
    print("신규 매수는 실행하지 않습니다.")
    print("입력한 매입가 기준으로 종목별 익절/DCA트리거 %를 적용해 익절가와 DCA트리거가를 자동 계산합니다.")
    print("※ 복구 실행 시 대상 종목의 기존 익절/예약 미체결 매도 주문을 먼저 취소한 뒤 다시 등록합니다.")

    target_codes: set[str] = set()
    plan_items: list[dict[str, Any]] = []

    # 1) 우선 현재 잔고를 조회해서 보유수량/매도가능수량을 보여줍니다.
    #    기존 익절 주문이 걸려 있으면 매도가능수량은 0일 수 있으므로 보유수량도 함께 사용합니다.
    balance_map = _get_balance_map(client, force_refresh=True)

    for raw in restore_items:
        stk_cd = _norm_code(raw["code"])
        if not stk_cd:
            continue
        target_codes.add(stk_cd)

        stk_nm = _target_name(stk_cd)
        buy_price = _safe_int(raw["buy_price"])
        take_profit_price = _calc_take_profit_price(stk_cd, buy_price)
        stop_loss_price = _calc_stop_loss_price(stk_cd, buy_price)

        if TEST_MODE:
            holding_qty = _test_sellable_qty(stk_cd, 0)
            sellable_qty = holding_qty
        else:
            holding_qty = _holding_qty_from_balance_map(balance_map, stk_cd)
            sellable_qty = _sellable_qty_from_balance_map(balance_map, stk_cd)

        now_price = 0
        try:
            now_price = _safe_int(client.get_last_price(stk_cd), 0)
        except Exception as exc:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 현재가 조회 실패: {exc}")

        plan_items.append(
            {
                "stk_nm": stk_nm,
                "stk_cd": stk_cd,
                "holding_qty": holding_qty,
                "sellable_qty_before_cancel": sellable_qty,
                "qty": sellable_qty,
                "buy_avg_price": buy_price,
                "now_price": now_price,
                "take_profit_pct": _take_profit_pct(stk_cd),
                "stop_loss_pct": _stop_loss_pct(stk_cd),
                "take_profit_price": take_profit_price,
                "stop_loss_price": stop_loss_price,
            }
        )

    print("\n재시작 실행 예정 내역")
    for item in plan_items:
        print(
            f"- {item['stk_nm']}[{item['stk_cd']}] "
            f"매입가 {format(item['buy_avg_price'], ',')}원 / "
            f"현재가 {format(item['now_price'], ',')}원 / "
            f"보유수량 {item['holding_qty']}주 / "
            f"현재 매도가능수량 {item['sellable_qty_before_cancel']}주 / "
            f"익절 {item['take_profit_pct']:.1f}% -> {format(item['take_profit_price'], ',')}원 / "
            f"DCA트리거 {item['stop_loss_pct']:.1f}% -> {format(item['stop_loss_price'], ',')}원"
        )

    if not auto_yes:
        if not _confirm_execution("기존 예약 매도 주문을 취소하고, 재시작 모드로 익절 재등록 후 DCA 감시를 시작하시겠습니까?"):
            print(f"[{_now()}] 사용자가 실행하지 않음을 선택했습니다. 프로그램을 종료합니다.")
            return
    else:
        print(f"[{_now()}] --yes 옵션이 있어 복구 실행 확인을 생략합니다.")

    # 2) 대상 종목의 기존 예약/익절 미체결 매도 주문을 먼저 취소합니다.
    if target_codes:
        if TEST_MODE:
            print(f"[{_now()}] [TEST] 복구 대상 기존 미체결 매도 주문 취소 생략 / 대상 {sorted(target_codes)}")
        else:
            print(f"[{_now()}] 복구 대상 기존 미체결 매도 주문 취소 시작 / 대상 {sorted(target_codes)}")
            cancel_results = _cancel_before_sell_by_codes(
                client,
                target_codes=target_codes,
                reason="복구 모드 기존 익절/예약 매도 주문 삭제",
            )
            print(f"[{_now()}] 복구 대상 기존 미체결 매도 주문 취소 처리 건수: {len(cancel_results)}")
            time.sleep(max(1.0, ORDER_CANCEL_WAIT_SEC))

    # 3) 취소 후 매도가능수량을 다시 조회한 뒤, 그 수량 기준으로 익절 주문을 재등록합니다.
    if TEST_MODE:
        refreshed_balance_map = {}
    else:
        refreshed_balance_map = _get_balance_map(client, force_refresh=True)

    stop_watch_items: list[dict[str, Any]] = []
    for item in plan_items:
        stk_nm = str(item["stk_nm"])
        stk_cd = _norm_code(item["stk_cd"])
        take_profit_price = int(item["take_profit_price"])
        stop_loss_price = int(item["stop_loss_price"])

        if TEST_MODE:
            holding_qty_after = _test_sellable_qty(stk_cd, int(item.get("holding_qty", 0)))
            sellable_qty_after = holding_qty_after
        else:
            holding_qty_after = _holding_qty_from_balance_map(refreshed_balance_map, stk_cd)
            sellable_qty_after = _sellable_qty_from_balance_map(refreshed_balance_map, stk_cd)

        qty = int(sellable_qty_after)
        print(
            f"[{_now()}] {stk_nm}[{stk_cd}] 복구 취소 후 수량 확인 / "
            f"보유 {holding_qty_after}주 / 매도가능 {sellable_qty_after}주"
        )

        if qty <= 0:
            if holding_qty_after > 0:
                print(
                    f"[{_now()}] {stk_nm}[{stk_cd}] 보유수량은 있으나 매도가능수량이 0주입니다. "
                    "기존 예약 주문 취소 반영이 늦거나 취소 실패 가능성이 있어 익절 재등록/DCA 감시에서 제외합니다."
                )
            else:
                print(f"[{_now()}] {stk_nm}[{stk_cd}] 보유수량이 없어 익절 재등록/DCA 감시에서 제외합니다.")
            continue

        try:
            tp_result = _place_take_profit_sell(client, stk_cd, qty, take_profit_price)
            take_profit_ord_no = _require_valid_order_no(tp_result.get("sell_ord_no"), f"{stk_cd} 복구 익절 지정가 매도 주문")
            print(
                f"[{_now()}] {stk_nm}[{stk_cd}] 복구 익절 지정가 재등록 / "
                f"주문번호 {take_profit_ord_no} / 수량 {qty}주 / 가격 {format(take_profit_price, ',')}원"
            )
        except Exception as exc:
            take_profit_ord_no = None
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 복구 익절 지정가 등록 실패: {exc}")
            print(
                f"[{_now()}] {stk_nm}[{stk_cd}] 익절 주문은 등록되지 않았지만, "
                "보유수량 보호를 위해 DCA 감시는 계속 등록합니다."
            )

        stop_watch_items.append(
            {
                "stk_nm": stk_nm,
                "stk_cd": stk_cd,
                "qty": qty,
                "buy_avg_price": int(item["buy_avg_price"]),
                "stop_loss_pct": float(item["stop_loss_pct"]),
                "stop_loss_price": stop_loss_price,
                "buy_ord_no": "RESTORE_MODE",
                "take_profit_ord_no": take_profit_ord_no,
                "take_profit_price": take_profit_price,
                "entry_price": buy_avg_price,
                "strategy_base_price": buy_avg_price,
                "state": STATE_NORMAL,
                "rebuy_count": 0,
                "dca_step": 0,
                "dca_reserve_total": 0,
                "dca_used_amount": 0,
            }
        )

    if STOP_LOSS_WATCH_ENABLED:
        _watch_stop_loss(client, stop_watch_items)
    else:
        print(f"[{_now()}] DCA트리거 자동 감시는 비활성화되어 있습니다.")


# ===============================
# 전체 시장가 매도 초기화 모드
# ===============================

def _run_sell_all_mode(client: KiwoomClient, auto_yes: bool = False) -> None:
    """현재 계좌의 미체결 주문을 먼저 모두 취소한 뒤, 보유 중인 모든 종목을 시장가로 매도합니다."""
    print("\n" + "=" * 72)
    print(f"[{_now()}] 전체 보유종목 시장가 매도 초기화 모드")
    print("=" * 72)
    print("※ 기존 익절 지정가 등 미체결 주문을 먼저 전체 취소한 뒤 시장가 매도합니다.")

    if not TEST_MODE and not hasattr(client, "get_my_all_stock"):
        raise AttributeError("KiwoomClient에 get_my_all_stock() 함수가 없습니다.")

    if not TEST_MODE and not hasattr(client, "place_sell_market"):
        raise AttributeError("KiwoomClient에 place_sell_market(stk_cd, qty) 함수가 없습니다.")

    if TEST_MODE:
        preview_items = []
        for target in TARGET_STOCKS:
            code = _norm_code(target["code"])
            qty = _test_sellable_qty(code, 0)
            if qty > 0:
                preview_items.append({"stk_cd": code, "stk_nm": target.get("name", code), "holding_qty": qty, "sellable_qty": qty})
    else:
        balance_map = _get_balance_map(client, force_refresh=True)
        preview_items = []
        for code, stock in balance_map.items():
            holding_qty = _holding_qty_from_stock(stock)
            sellable_qty = _safe_int(stock.get("trde_able_qty"), 0)
            name = stock.get("stk_nm") or stock.get("name") or code
            if holding_qty > 0 or sellable_qty > 0:
                preview_items.append({"stk_cd": code, "stk_nm": name, "holding_qty": holding_qty, "sellable_qty": sellable_qty})

    if not preview_items:
        print(f"[{_now()}] 보유종목이 없습니다.")
        return

    print("초기화 대상 보유종목")
    for item in preview_items:
        print(
            f"- {item['stk_nm']}[{item['stk_cd']}] "
            f"보유수량 {item['holding_qty']}주 / 현재 매도가능수량 {item['sellable_qty']}주"
        )

    if not auto_yes:
        if not _confirm_execution("미체결 주문을 전체 취소한 뒤 위 보유종목을 시장가로 매도하시겠습니까?"):
            print(f"[{_now()}] 사용자가 전체 초기화를 취소했습니다.")
            return

    if TEST_MODE:
        print(f"[{_now()}] [TEST] 미체결 전체 취소 생략")
    else:
        print(f"[{_now()}] 미체결 주문 전체 취소를 시작합니다.")
        holding_codes = {_norm_code(item["stk_cd"]) for item in preview_items}
        cancel_results = _cancel_unfilled_orders(client, target_codes=None, only_sell_orders=False, reason="전체 청산 전")
        # 전체 조회가 0건이어도 익절 주문이 걸려 매도가능수량이 0일 수 있으므로 보유종목별 매도 미체결도 추가 확인합니다.
        extra_cancel_results = _cancel_unfilled_orders_for_holdings(client, holding_codes, reason="전체 청산 전 보유종목별 추가 확인")
        cancel_results.extend(extra_cancel_results)
        print(f"[{_now()}] 미체결 취소 처리 건수: {len(cancel_results)}")
        time.sleep(ORDER_CANCEL_WAIT_SEC)

    # 취소 반영 후 다시 매도가능수량 확인
    if TEST_MODE:
        sell_items = []
        for item in preview_items:
            qty = int(item["sellable_qty"])
            if qty > 0:
                sell_items.append({"stk_cd": item["stk_cd"], "stk_nm": item["stk_nm"], "qty": qty})
    else:
        balance_map = _get_balance_map(client, force_refresh=True)
        sell_items = []
        for code, stock in balance_map.items():
            qty = _safe_int(stock.get("trde_able_qty"), 0)
            name = stock.get("stk_nm") or stock.get("name") or code
            holding_qty = _holding_qty_from_stock(stock)
            if qty > 0:
                sell_items.append({"stk_cd": code, "stk_nm": name, "qty": qty})
            elif holding_qty > 0:
                print(
                    f"[{_now()}] {name}[{code}] 보유수량은 {holding_qty}주이나 "
                    "미체결 취소 후에도 매도가능수량이 0주입니다. 시장가 매도에서 제외합니다."
                )

    if not sell_items:
        print(f"[{_now()}] 미체결 취소 후에도 시장가 매도 가능한 수량이 없습니다.")
        return

    print("시장가 매도 실행 종목")
    for item in sell_items:
        print(f"- {item['stk_nm']}[{item['stk_cd']}] 매도가능수량 {item['qty']}주")

    for item in sell_items:
        stk_cd = _norm_code(item["stk_cd"])
        stk_nm = str(item.get("stk_nm", stk_cd))
        try:
            if TEST_MODE:
                qty = int(item["qty"])
                sell_ord_no = "TEST_SELL_ALL_MARKET_NOT_SENT"
                print(f"[{_now()}] [TEST] {stk_nm}[{stk_cd}] 시장가 매도 생략 / 가상주문번호 {sell_ord_no} / 수량 {qty}주")
            else:
                # 종목별 매도 직전에 잔고를 다시 조회합니다.
                # 첫 번째 종목 매도 후 잔고/매도가능수량이 변해도 두 번째 종목에 잘못된 수량이 들어가지 않게 합니다.
                balance_map = _get_balance_map(client, force_refresh=True)
                stock = balance_map.get(stk_cd, {})
                qty = _safe_int(stock.get("trde_able_qty"), 0)
                holding_qty = _holding_qty_from_stock(stock)
                print(
                    f"[{_now()}] [전체청산] {stk_nm}[{stk_cd}] 매도 직전 확인 / "
                    f"보유 {holding_qty}주 / 매도가능 {qty}주"
                )
                if qty <= 0:
                    print(f"[{_now()}] [전체청산] {stk_nm}[{stk_cd}] 매도가능수량 0주로 시장가 매도 생략")
                    continue
                sell_ord_no = client.place_sell_market(stk_cd, qty)
                sell_ord_no = _require_valid_order_no(sell_ord_no, f"{stk_cd} 전체 시장가 매도")
                print(f"[{_now()}] [전체청산] {stk_nm}[{stk_cd}] 시장가 매도 접수 / 주문번호 {sell_ord_no} / 수량 {qty}주")
                time.sleep(1)
        except Exception as exc:
            print(f"[{_now()}] [전체청산] {stk_nm}[{stk_cd}] 시장가 매도 실패: {exc}")

    if not TEST_MODE:
        time.sleep(2)
    print(f"[{_now()}] 전체 청산 절차가 종료되었습니다. 청산 후 계좌 정보를 조회합니다.")
    _print_account_after_liquidation(client)


# ===============================
# main
# ===============================

def main() -> None:
    global float_timeout

    args = _parse_args()
    log_file = _setup_log_tee(args.log.strip() or None)
    restore_items, restore_auto_yes = _build_restore_items_from_config_and_args(args)

    set_test_mode(b_Tprint)
    print(f"TEST_MODE - {TEST_MODE} - [MAIN] KODEX SK하이닉스/삼성전자 단일종목레버리지 50:50 자동매수 APP 시작")
    print(f"BUY_ORDER_TYPE - {_buy_order_type()} - LIMIT이면 지정가 매수, MARKET이면 시장가 매수로 실행합니다.")
    if _buy_order_type() == "LIMIT":
        print(f"LIMIT_BUY_UP_PCT - {LIMIT_BUY_UP_PCT:.2f}% - 현재가보다 이 비율만큼 높은 가격을 호가단위 올림하여 지정가 매수합니다.")
    print(f"TAKE_PROFIT_REBUY_ENABLED - {TAKE_PROFIT_REBUY_ENABLED} - 익절 체결 시 같은 종목을 재매수합니다.")
    print(f"INITIAL_ENTRY_CASH_RATE - {INITIAL_ENTRY_CASH_RATE:.2f} - 최초 진입에 사용할 계좌 비율")
    print(f"DCA_RESERVE_CASH_RATE - {DCA_RESERVE_CASH_RATE:.2f} - DCA 물타기에 남겨둘 계좌 비율")
    print(f"DCA_BUDGET_WEIGHTS - {DCA_BUDGET_WEIGHTS} - DCA 단계별 예산 가중치")
    print(f"STOP_LOSS_PRICE_RESET_ENABLED - {STOP_LOSS_PRICE_RESET_ENABLED} - DCA트리거 도달 시 즉시 매도하지 않고 DCA트리거 기준가를 재설정합니다.")
    print(f"MAX_REBUY_PER_STOCK - {MAX_REBUY_PER_STOCK} - 익절 후 재매수와 DCA트리거가 재설정 합산 최대 횟수")
    print(f"RESET_TAKE_PROFIT_ON_STOP_RESET - {RESET_TAKE_PROFIT_ON_STOP_RESET} - DCA트리거 재설정 시 익절 주문도 새 기준가로 재등록")
    print(f"DEFAULT_TAKE_PROFIT_SCHEDULE - {DEFAULT_TAKE_PROFIT_SCHEDULE} - DCA트리거 회차별 기본 익절률")
    print(f"FORCE_EXIT_ENABLED - {FORCE_EXIT_ENABLED} / FORCE_EXIT_TIME - {FORCE_EXIT_TIME} - 시간이 되면 전체 청산 후 종료합니다.")

    BaseURL = KIWOOM_URL.strip() or os.getenv("KIWOOM_URL", "https://mockapi.kiwoom.com")
    app_key = KIWOOM_APP_KEY.strip() or os.getenv("KIWOOM_APP_KEY")
    app_secret = KIWOOM_APP_SECRET.strip() or os.getenv("KIWOOM_APP_SECRET")

    if not app_key or not app_secret:
        raise SystemExit("KIWOOM_APP_KEY, KIWOOM_APP_SECRET 값을 코드 상단에 입력하거나 환경변수로 설정하세요.")

    auth = KiwoomAuth(app_key, app_secret, BaseURL)
    access_token = auth.token() if hasattr(auth, "token") else auth._access_token
    time.sleep(1)

    client = KiwoomClient(access_token, is_paper=is_paper)
    time.sleep(1)

    if args.sell_all:
        print(f"[{_now()}] --sell-all 옵션이 있어 장시작 대기와 신규 매수를 PASS합니다.")
        _run_sell_all_mode(client, auto_yes=bool(args.yes))
        print(f"[{_now()}] 완료")
        _close_log_tee()
        return

    if restore_items:
        print(f"[{_now()}] 재시작/복구 설정이 있어 장시작 대기와 신규 매수를 PASS합니다.")
        _run_restore_mode(client, restore_items, auto_yes=restore_auto_yes)
        print(f"[{_now()}] 완료")
        _close_log_tee()
        return

    if TEST_MODE or b_Test:
        print(f"[TEST MODE] 장시작 예약시간 {start_time} PASS")
    else:
        wait_until(start_time)

    account_snapshot = _get_account_snapshot(client)
    cur_entr = _safe_int(account_snapshot.get("cur_entr"))

    _print_account_snapshot(account_snapshot)

    order_plans = _make_order_plan(client, cur_entr)
    _print_order_plan(order_plans, cur_entr)

    if args.yes:
        print(f"\n[{_now()}] --yes 옵션이 있어 확인 질문 없이 주문을 시작합니다.")
    else:
        if not _confirm_execution("위 내용으로 최초 50% 진입 매수를 실행하시겠습니까?"):
            print(f"[{_now()}] 사용자가 실행하지 않음을 선택했습니다. 프로그램을 종료합니다.")
            return
        print(f"\n[{_now()}] 사용자가 실행을 승인했습니다. 주문을 시작합니다.")

    results: list[dict[str, Any]] = []
    stop_watch_items: list[dict[str, Any]] = []

    for plan in order_plans:
        stk_cd = _norm_code(plan["stk_cd"])
        stk_nm = str(plan["stk_nm"])
        budget = int(plan["budget"])
        now_price = int(plan["now_price"])
        qty = int(plan["qty"])

        # 이전 종목 매수 이후 주문가능금액이 줄었거나 시장가 체결가가 높아질 수 있으므로
        # 실제 주문 직전 주문가능금액/현재가로 수량을 보수적으로 재계산합니다.
        if not TEST_MODE:
            try:
                cur_entr_now = _safe_int(client.get_current_entr(), 0)
                last_price_now = _safe_int(client.get_last_price(stk_cd), now_price)
                if _buy_order_type() == "LIMIT":
                    order_price_now = _calc_limit_buy_price(stk_cd, last_price_now)
                    safe_budget = min(budget, cur_entr_now)
                    safe_qty = int(safe_budget // order_price_now) if order_price_now > 0 else qty
                    budget_label = f"지정가주문가능예산 {format(safe_budget, ',')}원"
                else:
                    order_price_now = last_price_now
                    safe_budget = min(budget, int(cur_entr_now * MARKET_BUY_CASH_SAFETY_RATE))
                    safe_qty = int(safe_budget // last_price_now) if last_price_now > 0 else qty
                    budget_label = f"시장가안전예산 {format(safe_budget, ',')}원({MARKET_BUY_CASH_SAFETY_RATE*100:.0f}%)"

                if 0 < safe_qty < qty:
                    print(
                        f"[{_now()}] {stk_nm}[{stk_cd}] 주문 직전 수량 조정 / "
                        f"기존 {qty}주 -> {safe_qty}주 / "
                        f"주문가능금액 {format(cur_entr_now, ',')}원 / "
                        f"{budget_label} / "
                        f"현재가 {format(last_price_now, ',')}원 / 주문기준가 {format(order_price_now, ',')}원"
                    )
                    qty = safe_qty
                    now_price = last_price_now
            except Exception as exc:
                print(f"[{_now()}] {stk_nm}[{stk_cd}] 주문 직전 주문가능금액/현재가 재확인 실패: {exc}")

        print(
            f"[{_now()}] {stk_nm}[{stk_cd}] "
            f"배정금액 {format(budget, ',')}원 / 현재가 {format(now_price, ',')}원 / "
            f"매수방식 {_buy_order_type()} / 매수수량 {qty}주"
        )

        if qty < 1:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 매수 가능 수량이 0주라서 건너뜁니다.")
            continue

        try:
            oto_result = _place_buy_then_takeprofit(client=client, stk_cd=stk_cd, buy_price=now_price, qty=qty)
        except Exception as exc:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 주문 실패: {exc}")
            continue

        buy_ord_no = oto_result.get("buy_ord_no")
        buy_avg_price = int(oto_result.get("buy_avg_price") or now_price)
        filled_qty = int(oto_result.get("buy_qty") or qty)
        take_profit_price = int(oto_result.get("take_profit_price") or 0)
        take_profit_ord_no = oto_result.get("take_profit_ord_no")
        stop_loss_price = _calc_stop_loss_price(stk_cd, buy_avg_price)
        take_profit_pct = _take_profit_pct(stk_cd)
        stop_loss_pct = _stop_loss_pct(stk_cd)

        result = {
            "stk_nm": stk_nm,
            "stk_cd": stk_cd,
            "qty": filled_qty,
            "buy_avg_price": buy_avg_price,
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
            "buy_ord_no": buy_ord_no,
            "take_profit_ord_no": take_profit_ord_no,
        }
        results.append(result)
        _log_trade_event(
            event="BUY",
            stk_cd=stk_cd,
            stk_nm=stk_nm,
            qty=filled_qty,
            price=buy_avg_price,
            base_price=buy_avg_price,
            order_no=buy_ord_no,
            memo="최초 매수",
            state=STATE_NORMAL,
            cycle=0,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
        )

        stop_watch_items.append(
            {
                "stk_nm": stk_nm,
                "stk_cd": stk_cd,
                "qty": filled_qty,
                "buy_avg_price": buy_avg_price,
                "entry_price": buy_avg_price,
                "strategy_base_price": buy_avg_price,
                "state": STATE_NORMAL,
                "rebuy_count": 0,
                "dca_step": 0,
                "dca_reserve_total": int(plan.get("dca_reserve_budget", 0) or 0),
                "dca_used_amount": 0,
                "take_profit_pct": take_profit_pct,
                "take_profit_price": take_profit_price,
                "stop_loss_pct": stop_loss_pct,
                "stop_loss_price": stop_loss_price,
                "buy_ord_no": buy_ord_no,
                "take_profit_ord_no": take_profit_ord_no,
            }
        )

        print(
            f"[{_now()}] {stk_nm}[{stk_cd}] 매수/익절 등록 완료 "
            f"체결가 {format(buy_avg_price, ',')}원 / 수량 {filled_qty}주 / "
            f"익절주문번호 {take_profit_ord_no} / "
            f"익절가 {format(take_profit_price, ',')}원(+{take_profit_pct:.1f}%) / "
            f"DCA트리거감시가 {format(stop_loss_price, ',')}원(-{stop_loss_pct:.1f}%)"
        )

    print(f"\n[{_now()}] 주문 등록 결과")
    if not results:
        print("등록된 주문이 없습니다.")
    else:
        for item in results:
            print(
                f"- {item['stk_nm']}[{item['stk_cd']}] "
                f"{item['qty']}주 / 매수가 {format(item['buy_avg_price'], ',')}원 / "
                f"익절 {item['take_profit_pct']:.1f}% {format(item['take_profit_price'], ',')}원 / "
                f"DCA트리거 {item['stop_loss_pct']:.1f}% {format(item['stop_loss_price'], ',')}원 / "
                f"매수주문번호 {item['buy_ord_no']} / 익절주문번호 {item['take_profit_ord_no']}"
            )

    try:
        cur_entr_after = client.get_current_entr()
        print(f"[{_now()}] 주문 후 계좌 주문가능금액: {format(_safe_int(cur_entr_after), ',')}원")
    except Exception as exc:
        print(f"[{_now()}] 주문 후 계좌 주문가능금액 조회 실패: {exc}")

    if STOP_LOSS_WATCH_ENABLED:
        _watch_stop_loss(client, stop_watch_items)
    else:
        print(f"[{_now()}] DCA트리거 자동 감시는 비활성화되어 있습니다. STOP_LOSS_WATCH_ENABLED=True로 변경하면 감시를 시작합니다.")

    _print_trade_report()
    print(f"[{_now()}] 완료")
    _close_log_tee()


if __name__ == "__main__":
    main()
