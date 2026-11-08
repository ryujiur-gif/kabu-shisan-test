"""東証の休場判定。"""
from datetime import date, timedelta

import jpholiday


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return False
    return not jpholiday.is_holiday(d)


def previous_trading_day(d: date) -> date:
    p = d - timedelta(days=1)
    while not is_trading_day(p):
        p -= timedelta(days=1)
    return p
