def clamp_score(value, minimum=0, maximum=100):
    """
    Keep a score safely between minimum and maximum.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 50

    return max(minimum, min(maximum, value))


def calculate_overall_score(metrics):
    """
    Calculate the user's overall debate score.

    The AI can provide individual metrics, while this function
    produces a consistent final score.
    """

    argument_strength = clamp_score(
        metrics.get("argument_strength", 50)
    )

    evidence = clamp_score(
        metrics.get("evidence", 50)
    )

    logical_consistency = clamp_score(
        metrics.get("logical_consistency", 50)
    )

    relevance = clamp_score(
        metrics.get("relevance", 50)
    )

    persuasiveness = clamp_score(
        metrics.get("persuasiveness", 50)
    )

    overall = (
        argument_strength * 0.25
        + evidence * 0.20
        + logical_consistency * 0.25
        + relevance * 0.15
        + persuasiveness * 0.15
    )

    return round(overall)


def get_performance_level(score):
    """
    Convert numerical score into a human-readable level.
    """

    score = clamp_score(score)

    if score >= 90:
        return "Exceptional"

    if score >= 80:
        return "Strong"

    if score >= 70:
        return "Good"

    if score >= 60:
        return "Developing"

    if score >= 50:
        return "Needs Improvement"

    return "Weak"


def calculate_skill_delta(score):
    """
    Determine how much the user's skill profile should improve
    after an argument.
    """

    score = clamp_score(score)

    if score >= 90:
        return 5

    if score >= 80:
        return 4

    if score >= 70:
        return 3

    if score >= 60:
        return 2

    return 1
