#!/usr/bin/env python3
"""Legacy chord-duration estimator."""

import json
import math
import sys
from pathlib import Path


def main(argv):
    if len(argv) != 3:
        return 1
    source, target = Path(argv[1]), Path(argv[2])
    payload = json.loads(source.read_text(encoding="utf-8"))
    radius = 0.0
    sites = []
    for contact in payload["contacts"]:
        duration = (contact["t4_s"] - contact["t1_s"]) / 2.0
        distance = payload["sky_speed_km_s"] * duration
        sites.append(
            {
                "site_id": contact["site_id"],
                "center_time_s": (contact["t1_s"] + contact["t4_s"]) / 2.0,
                "impact_parameter_km": max(0.0, payload["star_radius_km"] - distance),
            }
        )
        radius = max(radius, max(0.0, distance - payload["star_radius_km"]))
    document = {
        "event_id": payload["event_id"],
        "status": "solved",
        "body_radius_km": radius,
        "sites": sites,
    }
    target.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
