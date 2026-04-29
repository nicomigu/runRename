from app.services.renamer import parse_workout_from_laps


def test_distance_based_intervals():
    """4x1k with 200m rest — times vary enough that only distance is consistent"""
    laps = [
        {"distance": 2000, "elapsed_time": 600},    # warmup
        {"distance": 1000, "elapsed_time": 230},     # work (fast)
        {"distance": 200, "elapsed_time": 60},        # rest
        {"distance": 1000, "elapsed_time": 250},     # work (slower)
        {"distance": 200, "elapsed_time": 58},        # rest
        {"distance": 1000, "elapsed_time": 238},     # work
        {"distance": 200, "elapsed_time": 62},        # rest
        {"distance": 1000, "elapsed_time": 260},     # work (slowest)
        {"distance": 200, "elapsed_time": 59},        # rest
        {"distance": 1500, "elapsed_time": 500},     # cooldown
    ]
    result = parse_workout_from_laps(laps)
    assert result is not None
    assert "4x1k" in result
    assert "rest" in result


def test_time_based_intervals():
    """3x3min with 90s rest"""
    laps = [
        {"distance": 1500, "elapsed_time": 500},     # warmup
        {"distance": 850, "elapsed_time": 180},       # work 3min
        {"distance": 300, "elapsed_time": 90},         # rest
        {"distance": 855, "elapsed_time": 182},       # work 3min
        {"distance": 300, "elapsed_time": 90},         # rest
        {"distance": 845, "elapsed_time": 178},       # work 3min
        {"distance": 300, "elapsed_time": 88},         # rest
        {"distance": 1200, "elapsed_time": 400},      # cooldown
    ]
    result = parse_workout_from_laps(laps)
    assert result is not None
    assert "3x3min" in result


def test_too_few_laps():
    laps = [
        {"distance": 1000, "elapsed_time": 300},
        {"distance": 1000, "elapsed_time": 300},
    ]
    assert parse_workout_from_laps(laps) is None


def test_no_rest_periods():
    """All middle laps >= 1000m — regular run with auto 1km laps"""
    laps = [
        {"distance": 1000, "elapsed_time": 300},
        {"distance": 1000, "elapsed_time": 295},
        {"distance": 1000, "elapsed_time": 302},
        {"distance": 1000, "elapsed_time": 298},
        {"distance": 1000, "elapsed_time": 305},
    ]
    assert parse_workout_from_laps(laps) is None


def test_inconsistent_work_intervals():
    """Work intervals vary too much in both time and distance"""
    laps = [
        {"distance": 1500, "elapsed_time": 500},
        {"distance": 1000, "elapsed_time": 240},     # work
        {"distance": 200, "elapsed_time": 60},
        {"distance": 500, "elapsed_time": 400},       # very different work
        {"distance": 200, "elapsed_time": 60},
        {"distance": 1200, "elapsed_time": 400},
    ]
    assert parse_workout_from_laps(laps) is None


def test_odd_index_lap_too_long():
    """A 'rest' lap is >= 1000m — not a structured workout"""
    laps = [
        {"distance": 1500, "elapsed_time": 500},
        {"distance": 1000, "elapsed_time": 240},
        {"distance": 1200, "elapsed_time": 360},      # rest lap too long
        {"distance": 1000, "elapsed_time": 245},
        {"distance": 1200, "elapsed_time": 355},
        {"distance": 1500, "elapsed_time": 500},
    ]
    assert parse_workout_from_laps(laps) is None


def test_400m_repeats():
    """5x400m — times vary so only distance is consistent"""
    laps = [
        {"distance": 1600, "elapsed_time": 500},     # warmup
        {"distance": 400, "elapsed_time": 75},         # work
        {"distance": 200, "elapsed_time": 60},         # rest
        {"distance": 405, "elapsed_time": 88},         # work
        {"distance": 200, "elapsed_time": 60},         # rest
        {"distance": 398, "elapsed_time": 70},         # work
        {"distance": 200, "elapsed_time": 62},         # rest
        {"distance": 402, "elapsed_time": 95},         # work
        {"distance": 200, "elapsed_time": 58},         # rest
        {"distance": 400, "elapsed_time": 82},         # work
        {"distance": 200, "elapsed_time": 61},         # rest
        {"distance": 1200, "elapsed_time": 400},      # cooldown
    ]
    result = parse_workout_from_laps(laps)
    assert result is not None
    assert "5x400m" in result


def test_single_middle_lap():
    """Only one middle lap — not enough for a workout"""
    laps = [
        {"distance": 1500, "elapsed_time": 500},
        {"distance": 1000, "elapsed_time": 240},
        {"distance": 1500, "elapsed_time": 500},
    ]
    assert parse_workout_from_laps(laps) is None
