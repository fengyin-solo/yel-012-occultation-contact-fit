#!/usr/bin/env python3
"""Four-contact occultation inversion."""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
import tempfile
from itertools import combinations, permutations
from pathlib import Path


TOP = {"event_id", "star_radius_km", "sky_speed_km_s", "contacts"}
CONTACT = {"site_id", "contact_times_s"}
SITE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{1,15}$")


class Refusal(Exception):
    def __init__(self, kind):
        self.kind = kind


def fail(kind):
    sys.stderr.write(f"运行拒收: {kind}\n")
    raise SystemExit(1)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def pairs_hook(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("BAD_INPUT")
        result[key] = value
    return result


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != TOP:
        raise Refusal("BAD_INPUT")
    event_id = payload["event_id"]
    if (
        not isinstance(event_id, str)
        or not 2 <= len(event_id) <= 48
        or event_id != event_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in event_id)
    ):
        raise Refusal("BAD_INPUT")
    radius = payload["star_radius_km"]
    speed = payload["sky_speed_km_s"]
    if not finite(radius) or not 0 < radius <= 1_000_000:
        raise Refusal("BAD_INPUT")
    if not finite(speed) or not 0 < speed <= 1000:
        raise Refusal("BAD_INPUT")
    contacts = payload["contacts"]
    if not isinstance(contacts, list) or not 2 <= len(contacts) <= 8:
        raise Refusal("BAD_INPUT")
    seen = set()
    cleaned = []
    for contact in contacts:
        if not isinstance(contact, dict) or set(contact) != CONTACT:
            raise Refusal("BAD_INPUT")
        site = contact["site_id"]
        if not isinstance(site, str) or not SITE_PATTERN.fullmatch(site) or site in seen:
            raise Refusal("BAD_INPUT")
        seen.add(site)
        times = contact["contact_times_s"]
        if (
            not isinstance(times, list)
            or len(times) != 6
            or any(not finite(value) for value in times)
            or len(set(times)) < 3
        ):
            raise Refusal("BAD_INPUT")
        cleaned.append({"site_id": site, "times": [float(value) for value in times]})
    return event_id, float(radius), float(speed), cleaned


def invert(event_id, star_radius, speed, contacts):
    candidates = []
    for contact in contacts:
        options = []
        for subset in combinations(contact["times"], 4):
            if len(set(subset)) < 3:
                continue
            for t1, t2, t3, t4 in permutations(subset):
                if not (t1 < t2 <= t3 < t4):
                    continue
                outer = (t4 - t1) / 2.0
                inner = (t3 - t2) / 2.0
                difference = outer * outer - inner * inner
                radius = speed * speed * difference / (4.0 * star_radius)
                if math.isfinite(radius) and radius > 0:
                    option = (radius, (t1, t2, t3, t4), (t1 + t4) / 2.0, outer)
                    if option not in options:
                        options.append(option)
        if not options:
            raise Refusal("BAD_GEOMETRY")
        candidates.append(options)

    assignments = []
    for anchor in candidates[0]:
        chosen = [anchor]
        for options in candidates[1:]:
            matched = [
                option
                for option in options
                if abs(option[0] - anchor[0]) <= 1e-8 * anchor[0]
            ]
            if len(matched) != 1:
                break
            chosen.append(matched[0])
        else:
            assignments.append(chosen)
    if len(assignments) != 1:
        raise Refusal("BAD_GEOMETRY")
    chosen = assignments[0]
    radii = [item[0] for item in chosen]
    body_radius = statistics.median(radii)
    if body_radius > star_radius:
        raise Refusal("BAD_GEOMETRY")
    sites = []
    for contact, selected in zip(contacts, chosen):
        radius, times, center, outer = selected
        if abs(radius - body_radius) > 1e-8 * body_radius:
            raise Refusal("BAD_GEOMETRY")
        square = (star_radius + body_radius) ** 2 - speed * speed * outer * outer
        if square < -1e-8:
            raise Refusal("BAD_GEOMETRY")
        sites.append(
            {
                "site_id": contact["site_id"],
                "center_time_s": center,
                "impact_parameter_km": math.sqrt(max(0.0, square)),
            }
        )
    return {
        "event_id": event_id,
        "status": "solved",
        "body_radius_km": body_radius,
        "sites": sites,
    }


def publish(target, payload):
    if not target.parent.is_dir() or target.is_dir() or not os.access(target.parent, os.W_OK):
        raise Refusal("IO_FAILURE")
    old = target.read_bytes() if target.exists() else None
    stage = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".occult-", dir=target.parent)
        stage = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, target)
        stage = None
    except OSError:
        if old is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(old)
        raise Refusal("IO_FAILURE")
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def main(argv):
    if len(argv) != 3:
        fail("BAD_INPUT")
    source, target = Path(argv[1]), Path(argv[2])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=pairs_hook)
        result = invert(*validate(payload))
        encoded = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        publish(target, encoded)
        return 0
    except Refusal as exc:
        fail(exc.kind)
    except (OSError, UnicodeError, ValueError):
        fail("BAD_INPUT")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
