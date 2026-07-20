import math
import random


def trajectory(
    start: tuple[int, int],
    end: tuple[int, int],
    duration_ms: int | None = None,
    rng: random.Random | None = None,
) -> tuple[list[tuple[int, int]], int]:
    rng = rng or random.SystemRandom()
    x1, y1 = start
    x2, y2 = end
    distance = math.hypot(x2 - x1, y2 - y1)
    if distance < 1:
        return [end], 0
    if duration_ms is None:
        baseline = max(180, min(900, 170 + distance * 0.55))
        duration_ms = round(baseline * rng.uniform(0.85, 1.15))
    steps = max(8, min(90, math.ceil(duration_ms / 16)))
    dx, dy = x2 - x1, y2 - y1
    normal_x, normal_y = -dy / distance, dx / distance
    bend = rng.uniform(-1, 1) * min(55, distance * 0.12)
    c1 = (
        x1 + dx * rng.uniform(0.20, 0.38) + normal_x * bend,
        y1 + dy * rng.uniform(0.20, 0.38) + normal_y * bend,
    )
    c2 = (
        x1 + dx * rng.uniform(0.62, 0.82) + normal_x * bend * 0.55,
        y1 + dy * rng.uniform(0.62, 0.82) + normal_y * bend * 0.55,
    )
    points = []
    for step in range(1, steps + 1):
        raw = step / steps
        t = raw * raw * (3 - 2 * raw)
        inverse = 1 - t
        x = (
            inverse**3 * x1
            + 3 * inverse**2 * t * c1[0]
            + 3 * inverse * t**2 * c2[0]
            + t**3 * x2
        )
        y = (
            inverse**3 * y1
            + 3 * inverse**2 * t * c1[1]
            + 3 * inverse * t**2 * c2[1]
            + t**3 * y2
        )
        if step != steps:
            x += rng.uniform(-0.7, 0.7)
            y += rng.uniform(-0.7, 0.7)
        point = round(x), round(y)
        if not points or point != points[-1]:
            points.append(point)
    if points[-1] != end:
        points.append(end)
    return points, duration_ms
