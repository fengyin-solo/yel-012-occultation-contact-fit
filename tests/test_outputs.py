"""Acceptance tests for the occultation contact inversion."""

import json
import math
import os
import subprocess
import sys

import pytest


ENTRY = os.environ.get("OCCULTATION_ENTRY", "/app/occultation_contact_fit.py")
RADIUS = 10.0
BODY_RADIUS = 1.5
SPEED = 5.0


def contact(site, center, impact):
    outer = math.sqrt((RADIUS + BODY_RADIUS) ** 2 - impact**2) / SPEED
    inner = math.sqrt((RADIUS - BODY_RADIUS) ** 2 - impact**2) / SPEED
    ordered = [center - outer, center - inner, center + inner, center + outer]
    order = {
        "PIN-01": [2, 0, 3, 1],
        "RIDGE-2": [3, 1, 0, 2],
        "VALLEY": [1, 3, 2, 0],
        "CENTRAL": [2, 0, 3, 1],
    }.get(site, [2, 0, 3, 1])
    recorded = [ordered[index] for index in order]
    recorded.extend([center + 70.0, center - 80.0])
    return {"site_id": site, "contact_times_s": recorded}


def sample():
    return {
        "event_id": "OCC-2026-17",
        "star_radius_km": RADIUS,
        "sky_speed_km_s": SPEED,
        "contacts": [
            contact("PIN-01", 100.0, 3.0),
            contact("RIDGE-2", 102.5, 5.0),
            contact("VALLEY", 101.25, 0.0),
        ],
    }


def write(path, document, raw=None):
    if raw is None:
        raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_bytes(raw.encode("utf-8"))
    return path


def invoke(tmp_path, document, raw=None, name="result"):
    source = write(tmp_path / "contacts.json", document, raw=raw)
    output = tmp_path / f"{name}.json"
    result = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, source, output


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_success_is_quiet(tmp_path):
    """题面：「命令行入口如下。」"""
    result, _, output = invoke(tmp_path, sample())
    assert result.returncode == 0 and result.stdout == "" and result.stderr == "" and output.is_file()


def test_body_radius_is_inverted_from_inner_and_outer_contacts(tmp_path):
    """题面：「r = v^2*(a^2-c^2)/(4*R)」。"""
    result, _, output = invoke(tmp_path, sample())
    assert result.returncode == 0 and read(output)["body_radius_km"] == pytest.approx(BODY_RADIUS)


def test_unordered_contacts_recover_unique_common_radius(tmp_path):
    """题面：「先从每个台站排除两个噪声时刻，再把剩余四个无序时刻恢复成唯一一组 `t1_s < t2_s <= t3_s < t4_s`。所有台站恢复出的半径必须落在同一个 `1e-8` 相对容差簇内。只有一个台站也有多个子集/排列可落入该簇，或不同台站没有任何共同一致组合时，视为对应关系无法唯一恢复。」"""
    result, _, output = invoke(tmp_path, sample())
    document = read(output)
    assert result.returncode == 0
    assert document["body_radius_km"] == pytest.approx(BODY_RADIUS, rel=1e-10)
    assert [item["site_id"] for item in document["sites"]] == ["PIN-01", "RIDGE-2", "VALLEY"]


def test_noise_candidates_are_excluded_by_common_radius(tmp_path):
    """题面：「其中恰好两个是录包噪声，另外四个是真实内外接触，但录包程序没有保存接触编号。」"""
    result, _, output = invoke(tmp_path, sample())
    document = read(output)
    assert result.returncode == 0
    assert document["body_radius_km"] == pytest.approx(BODY_RADIUS, rel=1e-10)
    assert len(document["sites"]) == 3


def test_impact_parameter_matches_each_station(tmp_path):
    """题面：「最终输出每站的 `b`，并用最终半径重新计算它。」"""
    result, _, output = invoke(tmp_path, sample())
    impacts = [item["impact_parameter_km"] for item in read(output)["sites"]]
    assert result.returncode == 0 and impacts == pytest.approx([3.0, 5.0, 0.0], abs=1e-6)


def test_center_time_uses_outer_contacts(tmp_path):
    """题面：「路径中心时刻为 `t0=(t1_s+t4_s)/2`。」"""
    result, _, output = invoke(tmp_path, sample())
    centers = [item["center_time_s"] for item in read(output)["sites"]]
    assert result.returncode == 0 and centers == pytest.approx([100.0, 102.5, 101.25])


def test_full_occultation_zero_inner_duration_is_supported(tmp_path):
    """题面：「恒星球心与天体边缘相交时发生外切。记恒星星半径为 `R`，掩食天体半径为 `r`，该站天空速度大小为 `v`。恢复出的正半径还必须满足 `r <= R`。外切到外切的半时长为 `a=(t4_s-t1_s)/2`，两次内切之间的半时长为 `c=(t3_s-t2_s)/2`，路径中心时刻为 `t0=(t1_s+t4_s)/2`。四接触满足：」"""
    payload = sample()
    payload["contacts"] = [
        contact("CENTRAL", 10.0, 0.0),
        contact("RIDGE-2", 12.0, 4.0),
    ]
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 0 and read(output)["body_radius_km"] == pytest.approx(BODY_RADIUS)


def test_top_level_keys_are_exact(tmp_path):
    """题面：「根对象四键均不可省略，也不接受第五个键。」"""
    payload = sample()
    payload["observer"] = "night"
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_contact_count_has_a_lower_bound(tmp_path):
    """题面：「`contacts` 含 2 到 8 个台站记录。」"""
    payload = sample()
    payload["contacts"] = payload["contacts"][:1]
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_contact_keys_are_exact(tmp_path):
    """题面：「一次台站观测的字段如下，不能增减：」。"""
    payload = sample()
    payload["contacts"][0]["filter"] = "R"
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_duplicate_json_key_is_bad_input(tmp_path):
    """题面：「联络单无法通过字段与时刻检查时，按以下终端约定结束：」。"""
    raw = (
        '{"event_id":"A1","star_radius_km":10,"sky_speed_km_s":5,'
        '"contacts":[{"site_id":"A-1","contact_times_s":[2,0,3,1]}],'
        '"contacts":[]}'
    )
    result, _, output = invoke(tmp_path, None, raw=raw)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


@pytest.mark.parametrize("event_id", ["A", " leading", "trailing ", "A" * 49, "A\nB"])
def test_event_identifier_is_strict(tmp_path, event_id):
    """题面：「批号 `event_id` 取 2 到 48 个可见字符，两端不能留空，控制字符也不可用。」"""
    payload = sample()
    payload["event_id"] = event_id
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_event_identifier_bounds_are_inclusive(tmp_path):
    """题面：「批号 `event_id` 取 2 到 48 个可见字符，两端不能留空，控制字符也不可用。」"""
    payload = sample()
    # case_id: EVENT-ID-ACCEPT
    payload["event_id"] = "A1"
    shortest, _, shortest_output = invoke(tmp_path, payload, name="shortest")
    payload["event_id"] = "A" * 48
    longest, _, longest_output = invoke(tmp_path, payload, name="longest")
    # case_id: EVENT-ID-REJECT
    payload["event_id"] = "A"
    too_short, _, missing_short = invoke(tmp_path, payload, name="too-short")
    payload["event_id"] = "A" * 49
    too_long, _, missing_long = invoke(tmp_path, payload, name="too-long")
    assert shortest.returncode == 0 and shortest_output.is_file()
    assert longest.returncode == 0 and longest_output.is_file()
    assert too_short.returncode == 1 and too_short.stderr == "运行拒收: BAD_INPUT\n"
    assert too_long.returncode == 1 and too_long.stderr == "运行拒收: BAD_INPUT\n"
    assert not missing_short.exists() and not missing_long.exists()


def test_duplicate_site_is_refused(tmp_path):
    """题面：「`site_id` 匹配 `[A-Z][A-Z0-9_-]{1,15}` 且不重复。」"""
    payload = sample()
    payload["contacts"][1]["site_id"] = payload["contacts"][0]["site_id"]
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


@pytest.mark.parametrize("times", [[10.0, 10.0, 11.0, 12.0, 13.0], [10.0] * 6])
def test_contact_times_require_six_values_and_three_distinct(tmp_path, times):
    """题面：「`site_id` 匹配 `[A-Z][A-Z0-9_-]{1,15}` 且不重复。`contact_times_s` 恰好是六个有限数。其中恰好两个是录包噪声，另外四个是真实内外接触，但录包程序没有保存接触编号。真实四时刻至少要有三个不同数值；允许全掩造成的中间两接触同刻。布尔值不算数字。」"""
    payload = sample()
    payload["contacts"][0]["contact_times_s"] = times
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_boolean_time_is_refused(tmp_path):
    """题面：「布尔值不算数字。」"""
    payload = sample()
    payload["contacts"][0]["contact_times_s"][0] = False
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_inconsistent_sites_are_bad_geometry(tmp_path):
    """题面：「多个台站给出的半径应当一致。以各站反演半径的中位数为最终半径；若任一站点与中位数的相对差超过 `1e-8`，说明四接触不自洽，不能用其中最好的一站掩盖问题。最终输出每站的 `b`，并用最终半径重新计算它。」"""
    payload = sample()
    site = payload["contacts"][1]
    site["contact_times_s"][0] -= 0.01
    site["contact_times_s"][1] += 0.01
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_GEOMETRY\n" and not output.exists()


def test_nonpositive_radius_is_bad_geometry(tmp_path):
    """题面：「恢复出的正半径还必须满足 `r <= R`。」"""
    payload = sample()
    payload["contacts"] = [
        {"site_id": "BAD-GEOM", "contact_times_s": [0.0, 1.0, 2.0, 100.0, 120.0, 140.0]},
        {"site_id": "BAD-GEOM2", "contact_times_s": [0.0, 1.0, 2.0, 100.0, 120.0, 140.0]},
    ]
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_GEOMETRY\n" and not output.exists()


def test_result_has_compact_fixed_order(tmp_path):
    """题面：「半径反演结果只占一行。JSON 字段之间不插空格。文件最后以 LF 封口。」"""
    result, _, output = invoke(tmp_path, sample())
    raw = output.read_bytes()
    document = json.loads(raw)
    assert result.returncode == 0
    assert list(document) == ["event_id", "status", "body_radius_km", "sites"]
    assert b": " not in raw and raw.endswith(b"\n") and raw.count(b"\n") == 1


def test_sites_preserve_input_order(tmp_path):
    """题面：「`sites` 按输入台站顺序排列。」"""
    payload = sample()
    result, _, output = invoke(tmp_path, payload)
    assert result.returncode == 0
    assert [item["site_id"] for item in read(output)["sites"]] == ["PIN-01", "RIDGE-2", "VALLEY"]


def test_sites_have_exact_keys(tmp_path):
    """题面：「每项字段如下：」。"""
    result, _, output = invoke(tmp_path, sample())
    assert result.returncode == 0
    assert all(set(item) == {"site_id", "center_time_s", "impact_parameter_km"} for item in read(output)["sites"])


def test_absent_parent_is_io_failure(tmp_path):
    """题面：「反演结果无处可写时，进程退出 1，标准错误写 `运行拒收: IO_FAILURE`，之前的结果继续保留。」"""
    source = write(tmp_path / "contacts.json", sample())
    output = tmp_path / "absent-parent" / "result.json"
    result = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1 and result.stderr == "运行拒收: IO_FAILURE\n" and not output.exists()


def test_bad_geometry_preserves_existing_result(tmp_path):
    """题面：「退回到终端时不得附带 Python 异常栈。」"""
    result, source, output = invoke(tmp_path, sample())
    before = output.read_bytes()
    payload = sample()
    payload["contacts"][0]["contact_times_s"][0] += 0.1
    write(source, payload)
    rejected = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and rejected.returncode == 1
    assert output.read_bytes() == before
    assert rejected.stderr.startswith("运行拒收: BAD_GEOMETRY") and rejected.stderr.count("\n") == 1


def test_repeat_run_is_byte_identical(tmp_path):
    """题面：「同一份台站联络单重跑时，输出字节必须一致。」"""
    result, source, output = invoke(tmp_path, sample())
    first = output.read_bytes()
    second = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and second.returncode == 0 and output.read_bytes() == first
