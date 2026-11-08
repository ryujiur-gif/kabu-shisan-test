from datetime import date
from kabu.market_calendar import is_trading_day, previous_trading_day

def test_weekday_is_trading_day():
    assert is_trading_day(date(2026, 11, 9))

def test_sunday_closed():
    assert not is_trading_day(date(2026, 11, 8))

def test_holiday_closed():
    assert not is_trading_day(date(2026, 11, 23))

def test_new_year_closed():
    assert not is_trading_day(date(2026, 12, 31))
    assert not is_trading_day(date(2027, 1, 2))

def test_previous_trading_day_skips_weekend_and_holiday():
    assert previous_trading_day(date(2026, 11, 24)) == date(2026, 11, 20)
