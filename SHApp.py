# ===============================
# file: SHApp.py
# ===============================
# file: SHApp_samsung_sk_oto.py
# version : 1.9.0
# ===============================
# python SHApp_samsung_sk_oto.py
#
# 기능 요약
# 1) 일반 모드
#    - 계좌 정보, 현재가, 예상 매수수량/금액 표시
#    - 사용자 승인 후 삼성전자/SK하이닉스 50:50 시장가 매수
#    - 체결 대기 중 진행상황 출력
#    - 체결가 기준 종목별 익절 %로 지정가 매도 등록
#    - 종목별 손절 % 가격을 계산하고, 손절 감시가 켜져 있으면 현재가 감시 후 해당 종목만 시장가 매도
#
# 2) 재시작/복구 모드
#    - 프로그램 강제 종료 후 다시 시작할 때 매수는 PASS
#    - 종목별 매입가만 입력하면 종목별 익절 % / 손절 %로 가격 자동 계산
#    - 계좌 보유/매도가능수량 확인
#    - 익절 지정가 재등록
#    - 손절 감시 진입
#
# 재시작 방법 1: 코드 상단 설정 사용
# RESTORE_MODE = True
# RESTORE_STOCKS = [
#     {"code": "005930", "buy_price": 75000},
#     {"code": "000660", "buy_price": 285000},
# ]
#
# 재시작 방법 2: 실행 파라미터 사용
# python SHApp_samsung_sk_oto.py --restore 005930:75000 000660:285000
# python SHApp_samsung_sk_oto.py --restore 005930:75000 000660:285000 --yes
#
# 주의
# place_loss_cut_sell()은 손절 예약 함수가 아니라 즉시 시장가 청산 계열 함수입니다.
# 이 파일은 손절 감시 중 손절가에 도달한 특정 종목만 매도가능수량 확인 후 시장가 매도합니다.

from __future__ import annotations

import os
import math
import time
import sys
import argparse
from datetime import datetime, timedelta
from typing import Any

from auth import KiwoomAuth
from kiwoom_client import KiwoomClient
from tools import *

app_key = os.getenv("KIWOOM_APP_KEY", "deNdUdk4RvyjwomX7RJtZRZ_6sIMQQvUlBHsvOk0C_w")
app_secret = os.getenv("KIWOOM_APP_SECRET", "T3KJAE_hhuHzfcJLqGvodUz4m3uqYTKQRECi1xgksGM")
print("account : cyKim...#81292993 26-06-25 ~ 26-07-25 김창연 1000만원 #")  

# ===============================
# 기본 실행 설정
# ===============================

# 00:00이면 즉시 시작, 예: "09:00"이면 해당 시간까지 대기
start_time: str = "00:00"

# 모의투자 여부. 실전은 False로 변경하세요.
is_paper: bool = True

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
# 익절/손절 %를 종목별로 분리했습니다.
# ===============================

TARGET_STOCKS: list[dict[str, Any]] = [
    {
        "code": "005930",
        "name": "삼성전자",
        "weight": 0.50,
        "take_profit_pct": 12.0,
        "stop_loss_pct": 6.0,
        "test_down_rate": 0.010,   # 손절 감시 TEST: 1초마다 -1.0%
        "test_sellable_qty": 10,   # TEST_FAKE_SELLABLE=True일 때 가상 매도가능수량
    },
    {
        "code": "000660",
        "name": "SK하이닉스",
        "weight": 0.50,
        "take_profit_pct": 12.0,
        "stop_loss_pct": 6.0,
        "test_down_rate": 0.015,   # 손절 감시 TEST: 1초마다 -1.5%
        "test_sellable_qty": 10,   # TEST_FAKE_SELLABLE=True일 때 가상 매도가능수량
    },
]

# ===============================
# 재시작/복구 모드 설정
# ===============================

# True이면 신규 매수는 하지 않고 RESTORE_STOCKS의 매입가 기준으로 익절/손절가를 계산합니다.
RESTORE_MODE: bool = False

# 형식: code + buy_price만 입력합니다.
# 익절가/손절가는 TARGET_STOCKS의 take_profit_pct, stop_loss_pct로 자동 계산합니다.
RESTORE_STOCKS: list[dict[str, Any]] = [
    # {"code": "005930", "buy_price": 75000},
    # {"code": "000660", "buy_price": 285000},
]

# RESTORE_MODE=True일 때 확인 질문 없이 바로 실행할지 여부
RESTORE_AUTO_YES: bool = False

# ===============================
# 손절 감시 설정
# ===============================

STOP_LOSS_WATCH_ENABLED: bool = True
STOP_LOSS_CHECK_SEC: float = 1.0
STOP_LOSS_PRINT_SEC: float = 1.0

# True이면 API 현재가 대신 종목별 가상 현재가를 사용합니다.
# 실제 운용 전에는 반드시 False로 바꾸세요.
# ===============================
# TEST OPTION
# ===============================

# TEST_MODE=True이면 아래 TEST_* 옵션을 사용합니다.
# 실전 전환 시 TEST_MODE=False, is_paper=False 여부를 반드시 다시 확인하세요.
TEST_MODE: bool = True

# 10초 후 체결 확인이 안 되어도 현재가로 가상 체결 처리합니다.
TEST_FAKE_FILL: bool = True
TEST_FILL_AFTER_SEC: float = 10.0

# 가상 체결 후에도 실제 익절 지정가 주문을 넣을지 여부입니다.
# TEST 중 실제 주문을 피하려면 False를 유지하세요.
TEST_PLACE_REAL_TAKE_PROFIT_AFTER_FAKE_FILL: bool = False

# 손절 감시에서 API 현재가 대신 종목별 가상 현재가를 사용합니다.
TEST_FAKE_PRICE: bool = True

# 손절 감시에서 계좌의 매도가능수량 대신 감시수량 또는 종목별 test_sellable_qty를 사용합니다.
TEST_FAKE_SELLABLE: bool = True

# 손절가 도달 시 실제 시장가 매도 주문을 넣을지 여부입니다.
# TEST 중 실제 주문을 피하려면 False를 유지하세요.
TEST_PLACE_REAL_STOP_LOSS_SELL: bool = False


# ===============================
# 공통 유틸
# ===============================

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
    return str(stk_cd).replace("A", "").strip()


def _target_by_code(stk_cd: str) -> dict[str, Any]:
    code = _norm_code(stk_cd)
    for target in TARGET_STOCKS:
        if _norm_code(target.get("code")) == code:
            return target
    return {
        "code": code,
        "name": code,
        "weight": 0.0,
        "take_profit_pct": 12.0,
        "stop_loss_pct": 6.0,
        "test_down_rate": 0.01,
        "test_sellable_qty": 10,
    }


def _target_name(stk_cd: str) -> str:
    return str(_target_by_code(stk_cd).get("name", _norm_code(stk_cd)))


def _take_profit_pct(stk_cd: str) -> float:
    return float(_target_by_code(stk_cd).get("take_profit_pct", 12.0))


def _stop_loss_pct(stk_cd: str) -> float:
    return float(_target_by_code(stk_cd).get("stop_loss_pct", 6.0))


def _test_down_rate(stk_cd: str) -> float:
    return float(_target_by_code(stk_cd).get("test_down_rate", 0.01))


def _test_sellable_qty(stk_cd: str, default_qty: int = 0) -> int:
    if default_qty and default_qty > 0:
        return int(default_qty)
    return int(_target_by_code(stk_cd).get("test_sellable_qty", 0) or 0)


def _calc_take_profit_price(stk_cd: str, buy_price: int) -> int:
    pct = _take_profit_pct(stk_cd)
    return floor_to(int(buy_price * (1 + pct / 100.0)), PRICE_UNIT)


def _calc_stop_loss_price(stk_cd: str, buy_price: int) -> int:
    pct = _stop_loss_pct(stk_cd)
    return floor_to(int(buy_price * (1 - pct / 100.0)), PRICE_UNIT)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="삼성전자/SK하이닉스 50:50 매수, 익절 등록, 손절 감시 APP")
    parser.add_argument(
        "--restore",
        nargs="*",
        default=[],
        metavar="CODE:BUY_PRICE",
        help="강제 종료 후 재시작 모드. 예: --restore 005930:75000 000660:285000",
    )
    parser.add_argument(
        "--restart",
        nargs="*",
        default=[],
        metavar="CODE:BUY_PRICE",
        help="--restore와 동일합니다. 기존 습관용 alias입니다.",
    )
    parser.add_argument("--yes", action="store_true", help="확인 질문 없이 실행합니다. 재시작 자동 실행용입니다.")
    return parser.parse_args()


def _parse_restore_args(values: list[str]) -> list[dict[str, Any]]:
    restore_items: list[dict[str, Any]] = []
    for raw in values:
        raw = str(raw).strip()
        if not raw:
            continue
        parts = raw.split(":")
        if len(parts) != 2:
            raise SystemExit("복구 형식이 잘못되었습니다. 예: --restore 005930:75000 000660:285000")
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


def _get_sellable_qty(client: KiwoomClient, stk_cd: str, default_qty: int = 0) -> int:
    """계좌 잔고에서 해당 종목의 매도가능수량만 조회합니다. TEST에서는 가상 수량을 사용할 수 있습니다."""
    target_code = _norm_code(stk_cd)

    if TEST_MODE and TEST_FAKE_SELLABLE:
        fake_qty = _test_sellable_qty(target_code, default_qty)
        print(f"[{_now()}] [TEST] {target_code} 매도가능수량을 가상값 {fake_qty}주로 사용합니다.")
        return fake_qty

    if not hasattr(client, "get_my_all_stock"):
        print(f"[{_now()}] KiwoomClient에 get_my_all_stock() 함수가 없어 매도가능수량을 확인할 수 없습니다.")
        return 0

    try:
        balance_info = client.get_my_all_stock()
    except Exception as exc:
        print(f"[{_now()}] {target_code} 잔고 조회 실패: {exc}")
        return 0

    for stock in balance_info:
        code = _norm_code(stock.get("stk_cd", ""))
        if code == target_code:
            return _safe_int(stock.get("trde_able_qty"), 0)

    return 0


def _make_order_plan(client: KiwoomClient, cur_entr: int) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []

    for target in TARGET_STOCKS:
        stk_cd = _norm_code(target["code"])
        stk_nm = str(target["name"])
        weight = float(target["weight"])
        budget = math.floor(cur_entr * weight)

        now_price = int(client.get_last_price(stk_cd))
        time.sleep(1)

        qty = int(budget // now_price) if now_price > 0 else 0
        expected_amount = qty * now_price
        remaining_budget = budget - expected_amount
        expected_take_profit_price = _calc_take_profit_price(stk_cd, now_price)
        expected_stop_loss_price = _calc_stop_loss_price(stk_cd, now_price)

        plans.append(
            {
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "weight": weight,
                "budget": budget,
                "now_price": now_price,
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
    print("50 / 50 실행 전 예상 매수 내역")
    print("=" * 72)

    total_expected = 0
    for plan in plans:
        total_expected += int(plan["expected_amount"])
        print(
            f"{plan['stk_nm']}[{plan['stk_cd']}] "
            f"비중 {plan['weight'] * 100:.0f}% / "
            f"배정금액 {format(plan['budget'], ',')}원 / "
            f"현재가 {format(plan['now_price'], ',')}원 / "
            f"예상수량 {plan['qty']}주 / "
            f"예상매수금액 {format(plan['expected_amount'], ',')}원 / "
            f"익절 {plan['take_profit_pct']:.1f}% -> {format(plan['expected_take_profit_price'], ',')}원 / "
            f"손절 {plan['stop_loss_pct']:.1f}% -> {format(plan['expected_stop_loss_price'], ',')}원"
        )

    print("-" * 72)
    print(f"총 예상 매수금액: {format(total_expected, ',')}원")
    print(f"예상 주문 후 잔여 주문가능금액: {format(cur_entr - total_expected, ',')}원")
    print("※ 시장가 주문이므로 실제 체결금액은 현재가 기준 예상금액과 달라질 수 있습니다.")
    print("※ 익절 지정가 매도는 주문 등록합니다.")
    print("※ 손절은 예약 등록이 아니라 감시 후 조건 충족 시 해당 종목만 시장가 매도합니다.")


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

def _place_take_profit_sell(client: KiwoomClient, stk_cd: str, qty: int, sell_price: int) -> dict[str, Any]:
    """지정가 익절 매도 주문을 등록합니다."""
    if qty <= 0:
        return {"sell_ord_no": None, "qty": qty, "price": sell_price, "reason": "qty <= 0"}

    if hasattr(client, "place_sell_limit"):
        sell_ord_no = client.place_sell_limit(stk_cd=stk_cd, qty=qty, price=sell_price)
        return {"sell_ord_no": sell_ord_no, "qty": qty, "price": sell_price, "method": "place_sell_limit"}

    if hasattr(client, "place_limit_sell"):
        result = client.place_limit_sell(stk_cd=stk_cd, qty=qty, price=sell_price)
        return {"sell_ord_no": result, "qty": qty, "price": sell_price, "method": "place_limit_sell"}

    if hasattr(client, "place_limit_sell_order"):
        result = client.place_limit_sell_order(stk_cd=stk_cd, qty=qty, price=sell_price)
        return {"sell_ord_no": result, "qty": qty, "price": sell_price, "method": "place_limit_sell_order"}

    if hasattr(client, "place_sell_order"):
        result = client.place_sell_order(stk_cd=stk_cd, qty=qty, price=sell_price, hoga_gb="00")
        return {"sell_ord_no": result, "qty": qty, "price": sell_price, "method": "place_sell_order"}

    raise AttributeError("KiwoomClient에 지정가 매도 함수가 없습니다. place_sell_limit(stk_cd, qty, price)를 확인하세요.")


def _place_market_buy_then_takeprofit(client: KiwoomClient, stk_cd: str, buy_price: int, qty: int) -> dict[str, Any]:
    """시장가 매수 -> 체결 폴링 표시 -> 종목별 익절 지정가 매도 등록."""
    take_profit_pct = _take_profit_pct(stk_cd)

    if b_Test:
        buy_avg_price = buy_price
        take_profit_price = _calc_take_profit_price(stk_cd, buy_avg_price)
        return {
            "buy_ord_no": "TEST_BUY",
            "buy_avg_price": buy_avg_price,
            "buy_qty": qty,
            "take_profit_ord_no": "TEST_TP",
            "take_profit_price": take_profit_price,
            "is_fake_filled": True,
        }

    if not hasattr(client, "place_buy_market"):
        raise AttributeError("KiwoomClient에 place_buy_market(stk_cd, qty) 함수가 없습니다.")
    if not hasattr(client, "get_order_fill_summary"):
        raise AttributeError("KiwoomClient에 get_order_fill_summary(ord_no) 함수가 없습니다.")

    buy_ord_no = client.place_buy_market(stk_cd=stk_cd, qty=qty)
    print(f"[{_now()}] {stk_cd} 시장가 매수 주문 접수 / 주문번호 {buy_ord_no} / 주문수량 {qty}주")

    start_ts = time.time()
    deadline = start_ts + float_timeout
    fake_fill_ts = start_ts + TEST_FILL_AFTER_SEC if (TEST_MODE and TEST_FAKE_FILL) else None
    buy_avg_price: int | None = None
    filled_qty: int = 0
    ord_qty: int = qty
    poll_count = 0
    is_fake_filled = False

    while time.time() < deadline:
        poll_count += 1
        now_ts = time.time()
        remain_sec = max(0, int(deadline - now_ts))
        elapsed_sec = int(now_ts - start_ts)

        if fake_fill_ts is not None and now_ts >= fake_fill_ts:
            last_price = client.get_last_price(stk_cd)
            buy_avg_price = _safe_int(last_price, buy_price)
            filled_qty = qty
            ord_qty = qty
            is_fake_filled = True
            print(
                f"[{_now()}] {stk_cd} TEST 강제 체결 처리 / "
                f"경과 {elapsed_sec}초 / 체결가 {format(buy_avg_price, ',')}원 / 체결수량 {filled_qty}주"
            )
            break

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

    if buy_avg_price is None:
        buy_avg_price = buy_price
        print(f"[{_now()}] {stk_cd} 체결 확인 Timeout {int(float_timeout)}초. 보정값으로 현재가 {format(buy_price, ',')}원을 사용합니다.")

    if filled_qty <= 0:
        filled_qty = ord_qty if ord_qty > 0 else qty
        print(f"[{_now()}] {stk_cd} 체결수량을 확인하지 못해 주문수량 {filled_qty}주로 보정합니다.")

    take_profit_price = _calc_take_profit_price(stk_cd, buy_avg_price)

    if is_fake_filled and not TEST_PLACE_REAL_TAKE_PROFIT_AFTER_FAKE_FILL:
        take_profit_ord_no = "TEST_TAKE_PROFIT_NOT_SENT"
        print(
            f"[{_now()}] {stk_cd} TEST 익절 지정가 매도 등록 생략 / "
            f"가상주문번호 {take_profit_ord_no} / 수량 {filled_qty}주 / "
            f"가격 {format(take_profit_price, ',')}원(+{take_profit_pct:.1f}%)"
        )
    else:
        tp_result = _place_take_profit_sell(client, stk_cd, filled_qty, take_profit_price)
        take_profit_ord_no = tp_result.get("sell_ord_no")
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
        "is_fake_filled": is_fake_filled,
    }


def _cancel_take_profit_order(client: KiwoomClient, sell_ord_no: Any, stk_cd: str, qty: int) -> Any:
    """손절 시장가 매도 전, 이미 걸어둔 익절 지정가 주문만 취소합니다."""
    if not sell_ord_no:
        return None

    if str(sell_ord_no).startswith("TEST_"):
        return "TEST_CANCEL_SKIPPED"

    if hasattr(client, "place_sell_order_cancel"):
        return client.place_sell_order_cancel(str(sell_ord_no), stk_cd, qty)

    if hasattr(client, "cancel_order"):
        return client.cancel_order(ord_no=str(sell_ord_no), stk_cd=stk_cd, qty=qty)

    print(f"[{_now()}] {stk_cd} 익절 주문 취소 함수가 없어 취소 없이 손절 매도를 진행합니다.")
    return None


def _place_stop_loss_market_sell(client: KiwoomClient, item: dict[str, Any], sellable_qty: int) -> dict[str, Any]:
    """손절가 도달 종목만 매도가능수량 기준으로 시장가 매도합니다."""
    stk_cd = _norm_code(item["stk_cd"])
    watch_qty = int(item.get("qty", 0))
    qty = min(watch_qty, int(sellable_qty)) if watch_qty > 0 else int(sellable_qty)
    take_profit_ord_no = item.get("take_profit_ord_no")

    if qty <= 0:
        return {"sell_ord_no": None, "reason": "sellable_qty <= 0"}

    cancel_result = _cancel_take_profit_order(client, take_profit_ord_no, stk_cd, qty)
    time.sleep(1)

    refreshed_sellable_qty = _get_sellable_qty(client, stk_cd, qty)
    qty = min(qty, refreshed_sellable_qty)
    if qty <= 0:
        return {"cancel_result": cancel_result, "sell_ord_no": None, "reason": "sellable_qty became 0 after cancel"}

    if TEST_MODE and not TEST_PLACE_REAL_STOP_LOSS_SELL:
        sell_ord_no = "TEST_STOP_LOSS_MARKET_NOT_SENT"
        print(f"[{_now()}] [TEST] {stk_cd} 실제 손절 시장가 매도 주문 생략 / 가상주문번호 {sell_ord_no} / 수량 {qty}주")
        return {"cancel_result": cancel_result, "sell_ord_no": sell_ord_no, "qty": qty, "method": "test_place_sell_market_skipped"}

    if hasattr(client, "place_sell_market"):
        sell_ord_no = client.place_sell_market(stk_cd, qty)
        return {"cancel_result": cancel_result, "sell_ord_no": sell_ord_no, "qty": qty, "method": "place_sell_market"}

    if hasattr(client, "place_loss_cut_sell"):
        loss_result = client.place_loss_cut_sell(buy_ord_no=str(take_profit_ord_no or item.get("buy_ord_no")), stk_cd=stk_cd, qty=qty)
        return {"cancel_result": cancel_result, "loss_result": loss_result, "qty": qty, "method": "place_loss_cut_sell_fallback"}

    raise AttributeError("KiwoomClient에 place_sell_market(stk_cd, qty) 함수가 없습니다.")


# ===============================
# 손절 감시
# ===============================

def _watch_stop_loss(client: KiwoomClient, watch_items: list[dict[str, Any]]) -> None:
    if not watch_items:
        print(f"[{_now()}] 손절 감시 대상이 없습니다.")
        return

    if not hasattr(client, "place_sell_market") and not hasattr(client, "place_loss_cut_sell"):
        print(f"[{_now()}] KiwoomClient에 손절 매도 함수가 없어 손절 감시를 시작하지 않습니다.")
        return

    active = {_norm_code(item["stk_cd"]): item for item in watch_items if int(item.get("qty", 0)) > 0}
    last_print_time = 0.0
    virtual_prices: dict[str, int] = {}

    print("\n" + "=" * 72)
    print(f"[{_now()}] 종목별 손절 감시 시작")
    print("=" * 72)
    for item in active.values():
        stk_cd = _norm_code(item["stk_cd"])
        print(
            f"{item['stk_nm']}[{stk_cd}] "
            f"감시수량 {item['qty']}주 / "
            f"매입가 {format(_safe_int(item.get('buy_avg_price')), ',')}원 / "
            f"손절 {item.get('stop_loss_pct', _stop_loss_pct(stk_cd)):.1f}% -> {format(item['stop_loss_price'], ',')}원 / "
            f"익절주문번호 {item.get('take_profit_ord_no')}"
        )

    if TEST_MODE and TEST_FAKE_PRICE:
        print("[TEST] 손절 감시 현재가는 API 가격이 아니라 종목별 가상 가격을 사용합니다.")
        for item in active.values():
            stk_cd = _norm_code(item["stk_cd"])
            print(f"[TEST] {item['stk_nm']}[{stk_cd}] 1초마다 -{_test_down_rate(stk_cd) * 100:.1f}%")

    print("Ctrl+C를 누르면 손절 감시를 중단합니다.")

    try:
        while active:
            remove_codes: list[str] = []
            now_ts = time.time()
            should_print = (now_ts - last_print_time) >= STOP_LOSS_PRINT_SEC

            for stk_cd, item in list(active.items()):
                stop_price = int(item["stop_loss_price"])

                # 익절 예약으로 이미 팔렸을 수 있으므로 매번 계좌의 매도가능수량을 확인합니다.
                sellable_qty = _get_sellable_qty(client, stk_cd, int(item.get("qty", 0)))
                item["sellable_qty"] = sellable_qty
                if sellable_qty <= 0:
                    print(
                        f"[{_now()}] {item['stk_nm']}[{stk_cd}] 매도가능수량이 0주입니다. "
                        "익절 체결 또는 보유수량 없음으로 판단하여 손절 감시에서 제외합니다."
                    )
                    remove_codes.append(stk_cd)
                    continue

                if TEST_MODE and TEST_FAKE_PRICE:
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
                        print(
                            f"[{_now()}] [TEST] 손절 감시 중 / {item['stk_nm']}[{stk_cd}] "
                            f"가상현재가 {format(last_price, ',')}원 / "
                            f"감소율 {rate * 100:.1f}% / "
                            f"손절가 {format(stop_price, ',')}원 / "
                            f"감시수량 {item['qty']}주 / 매도가능수량 {sellable_qty}주"
                        )
                else:
                    try:
                        last_price = int(client.get_last_price(stk_cd))
                    except Exception as exc:
                        print(f"[{_now()}] {item['stk_nm']}[{stk_cd}] 현재가 조회 실패: {exc}")
                        continue

                    if should_print:
                        print(
                            f"[{_now()}] 손절 감시 중 / {item['stk_nm']}[{stk_cd}] "
                            f"현재가 {format(last_price, ',')}원 / "
                            f"손절가 {format(stop_price, ',')}원 / "
                            f"감시수량 {item['qty']}주 / 매도가능수량 {sellable_qty}주"
                        )

                if last_price <= stop_price:
                    print(
                        f"[{_now()}] {item['stk_nm']}[{stk_cd}] 손절가 도달. "
                        f"현재가 {format(last_price, ',')}원 <= 손절가 {format(stop_price, ',')}원. "
                        f"해당 종목만 시장가 매도합니다."
                    )
                    loss_result = _place_stop_loss_market_sell(client, item, sellable_qty)
                    print(f"[{_now()}] {item['stk_nm']}[{stk_cd}] 손절 실행 결과: {loss_result}")
                    remove_codes.append(stk_cd)

                time.sleep(STOP_LOSS_CHECK_SEC)

            if should_print:
                last_print_time = now_ts

            for stk_cd in remove_codes:
                active.pop(stk_cd, None)

        print(f"[{_now()}] 모든 손절 감시 대상이 종료되었습니다.")

    except KeyboardInterrupt:
        print(f"\n[{_now()}] 사용자 중단(Ctrl+C). 손절 감시를 종료합니다.")


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
    print("입력한 매입가 기준으로 종목별 익절/손절 %를 적용해 익절가와 손절가를 자동 계산합니다.")

    plan_items: list[dict[str, Any]] = []
    for raw in restore_items:
        stk_cd = _norm_code(raw["code"])
        stk_nm = _target_name(stk_cd)
        buy_price = _safe_int(raw["buy_price"])
        take_profit_price = _calc_take_profit_price(stk_cd, buy_price)
        stop_loss_price = _calc_stop_loss_price(stk_cd, buy_price)
        sellable_qty = _get_sellable_qty(client, stk_cd)

        now_price = 0
        try:
            now_price = _safe_int(client.get_last_price(stk_cd), 0)
        except Exception as exc:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 현재가 조회 실패: {exc}")

        plan_items.append(
            {
                "stk_nm": stk_nm,
                "stk_cd": stk_cd,
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
            f"매도가능수량 {item['qty']}주 / "
            f"익절 {item['take_profit_pct']:.1f}% -> {format(item['take_profit_price'], ',')}원 / "
            f"손절 {item['stop_loss_pct']:.1f}% -> {format(item['stop_loss_price'], ',')}원"
        )

    if not auto_yes:
        if not _confirm_execution("재시작 모드로 익절 등록 후 손절 감시를 시작하시겠습니까?"):
            print(f"[{_now()}] 사용자가 실행하지 않음을 선택했습니다. 프로그램을 종료합니다.")
            return

    stop_watch_items: list[dict[str, Any]] = []
    for item in plan_items:
        stk_nm = str(item["stk_nm"])
        stk_cd = _norm_code(item["stk_cd"])
        qty = int(item["qty"])
        take_profit_price = int(item["take_profit_price"])
        stop_loss_price = int(item["stop_loss_price"])

        if qty <= 0:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 매도가능수량이 0주입니다. 익절 등록/손절 감시에서 제외합니다.")
            continue

        try:
            tp_result = _place_take_profit_sell(client, stk_cd, qty, take_profit_price)
            take_profit_ord_no = tp_result.get("sell_ord_no")
            print(
                f"[{_now()}] {stk_nm}[{stk_cd}] 재시작 익절 지정가 등록 / "
                f"주문번호 {take_profit_ord_no} / 수량 {qty}주 / 가격 {format(take_profit_price, ',')}원"
            )
        except Exception as exc:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 익절 지정가 등록 실패: {exc}")
            take_profit_ord_no = None

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
            }
        )

    if STOP_LOSS_WATCH_ENABLED:
        _watch_stop_loss(client, stop_watch_items)
    else:
        print(f"[{_now()}] 손절 자동 감시는 비활성화되어 있습니다.")


# ===============================
# main
# ===============================

def main() -> None:
    global float_timeout

    args = _parse_args()
    restore_items, restore_auto_yes = _build_restore_items_from_config_and_args(args)

    set_test_mode(b_Tprint)
    print(f"TEST Mode - {b_Test} - [MAIN] 삼성전자/SK하이닉스 50:50 자동매수 APP 시작")

    BaseURL = os.getenv("KIWOOM_URL", "https://mockapi.kiwoom.com")

    if not app_key or not app_secret:
        raise SystemExit("KIWOOM_APP_KEY, KIWOOM_APP_SECRET 환경변수를 설정하세요.")

    auth = KiwoomAuth(app_key, app_secret, BaseURL)
    access_token = auth.token() if hasattr(auth, "token") else auth._access_token
    time.sleep(1)

    client = KiwoomClient(access_token, is_paper=is_paper)
    time.sleep(1)

    if restore_items:
        print(f"[{_now()}] 재시작/복구 설정이 있어 장시작 대기와 신규 매수를 PASS합니다.")
        _run_restore_mode(client, restore_items, auto_yes=restore_auto_yes)
        print(f"[{_now()}] 완료")
        return

    if b_Test:
        print(f"[TEST MODE] 장시작 예약시간 {start_time} PASS")
        float_timeout = 1
    else:
        wait_until(start_time)

    account_snapshot = _get_account_snapshot(client)
    cur_entr = _safe_int(account_snapshot.get("cur_entr"))

    _print_account_snapshot(account_snapshot)

    order_plans = _make_order_plan(client, cur_entr)
    _print_order_plan(order_plans, cur_entr)

    if not _confirm_execution("위 내용으로 50 / 50 시장가 매수를 실행하시겠습니까?"):
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

        print(
            f"[{_now()}] {stk_nm}[{stk_cd}] "
            f"배정금액 {format(budget, ',')}원 / 현재가 {format(now_price, ',')}원 / 매수수량 {qty}주"
        )

        if qty < 1:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 매수 가능 수량이 0주라서 건너뜁니다.")
            continue

        try:
            oto_result = _place_market_buy_then_takeprofit(client=client, stk_cd=stk_cd, buy_price=now_price, qty=qty)
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

        stop_watch_items.append(
            {
                "stk_nm": stk_nm,
                "stk_cd": stk_cd,
                "qty": filled_qty,
                "buy_avg_price": buy_avg_price,
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
            f"손절감시가 {format(stop_loss_price, ',')}원(-{stop_loss_pct:.1f}%)"
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
                f"손절 {item['stop_loss_pct']:.1f}% {format(item['stop_loss_price'], ',')}원 / "
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
        print(f"[{_now()}] 손절 자동 감시는 비활성화되어 있습니다. STOP_LOSS_WATCH_ENABLED=True로 변경하면 감시를 시작합니다.")

    print(f"[{_now()}] 완료")


if __name__ == "__main__":
    main()
