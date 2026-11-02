from datetime import datetime, timezone

from fpl_agent.ingestion.matchday_conditions import kickoff_forecast, parse_conditions
from fpl_agent.monitoring.api.map_payload import _km


def test_conditions_read_the_ground_and_the_referee():
    payload = {"content": {"matchFacts": {"infoBox": {
        "Stadium": {"name": "Anfield", "city": "Liverpool", "lat": 53.43, "long": -2.96, "capacity": 61276},
        "Referee": {"text": "Andy Madley", "stats": [
            {"type": "matches", "value": 120}, {"type": "yellowCards", "value": 3.48, "average": 3.86},
            {"type": "redCards", "value": 3}, {"type": "penalties", "value": 21}, {"type": "fouls", "value": 20.1}]},
    }}}}
    c = parse_conditions(payload)
    assert (c["stadium"], c["lat"], c["lon"], c["capacity"]) == ("Anfield", 53.43, -2.96, 61276)
    assert (c["referee"], c["ref_matches"], c["ref_yellows_pm"], c["ref_yellows_avg"], c["ref_penalties"]) == ("Andy Madley", 120, 3.48, 3.86, 21)
    assert parse_conditions({"content": {"matchFacts": {"infoBox": {"Referee": {"text": ""}}}}})["referee"] is None


class _Session:
    def get(self, url, params, timeout):
        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"hourly": {"time": ["2026-11-07T19:00", "2026-11-07T20:00"], "temperature_2m": [9.1, 8.6],
                                   "precipitation_probability": [20, 45], "precipitation": [0, 0.4], "wind_speed_10m": [11, 14],
                                   "wind_gusts_10m": [25, 31], "weather_code": [3, 61]}}
        return R()


def test_forecast_is_the_kickoff_hour():
    wx = kickoff_forecast(51.5, -0.1, datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc), session=_Session())
    assert (wx["forecast_temp"], wx["forecast_precip_prob"], wx["forecast_code"], wx["forecast_gust"]) == (8.6, 45, 61, 31)
    assert kickoff_forecast(51.5, -0.1, datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc), session=_Session()) is None


def test_journey_distance_is_great_circle():
    assert round(_km((51.555, -0.108), (53.431, -2.961))) == 284
