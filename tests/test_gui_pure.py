"""The native UI's decision logic, tested without Qt.

Everything below ``gui/backend.py`` is plain Python precisely so it can be exercised here: no
window, no PySide6, no device. These are the rules a reviewer most needs pinned — above all
which bytes a write plan actually rewrites.
"""

from datetime import datetime, timedelta, timezone

import pytest

from nwupdater.gui import roster as R
from nwupdater.gui.format import APP_COLORS, color_for, fmt_bytes, fmt_relative, initial_for
from nwupdater.gui.plan import APP_SECTOR, Slot, Stage, footprint, plan_for
from nwupdater.gui.workshop import ROW_FIELDS, Workshop

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


# -- formatting -------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("size", "text"),
    [(0, "0 o"), (83, "83 o"), (1024, "1 Kio"), (65536, "64 Kio"), (3145728, "3 Mio")],
)
def test_fmt_bytes_uses_binary_units(size, text):
    assert fmt_bytes(size) == text


def test_fmt_bytes_tolerates_none():
    assert fmt_bytes(None) == "0 o"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "à l'instant"),
        (timedelta(minutes=20), "il y a 20 min"),
        (timedelta(hours=5), "il y a 5 h"),
        (timedelta(days=3), "il y a 3 j"),
    ],
)
def test_fmt_relative(delta, expected):
    assert fmt_relative((NOW - delta).isoformat(), now=NOW) == expected


@pytest.mark.parametrize("value", [None, "", "not-a-date"])
def test_fmt_relative_rejects_junk(value):
    assert fmt_relative(value, now=NOW) == "—"


def test_fmt_relative_assumes_utc_when_naive():
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    assert fmt_relative(naive, now=NOW) == "il y a 2 h"


def test_color_is_stable_and_in_palette():
    assert color_for("Tetris") == color_for("Tetris")
    assert color_for("Tetris") in APP_COLORS
    assert color_for("") in APP_COLORS  # never raises on an empty name


def test_initial_for():
    assert initial_for("tetris") == "T"
    assert initial_for("") == "?"


# -- footprint --------------------------------------------------------------------------
def test_apps_round_up_to_a_whole_flash_sector():
    assert footprint("apps", 1) == APP_SECTOR
    assert footprint("apps", APP_SECTOR) == APP_SECTOR
    assert footprint("apps", APP_SECTOR + 1) == 2 * APP_SECTOR
    assert footprint("apps", 0) == 0


def test_scripts_are_packed_byte_for_byte():
    assert footprint("scripts", 83) == 83
    assert footprint("scripts", 0) == 0


# -- the write plan ---------------------------------------------------------------------
DEVICE = [
    {"name": "Periodic", "size": 61440},
    {"name": "Chess", "size": 135168},
    {"name": "Snake", "size": 28672},
]


def stage() -> Stage:
    return Stage("apps", DEVICE, 3145728)


def test_untouched_device_is_not_dirty():
    plan = stage().plan()
    assert plan.status == ("un", "un", "un")
    assert (plan.un, plan.rw, plan.nw) == (3, 0, 0)
    assert plan.dirty is False


def test_appending_keeps_the_frozen_prefix_intact():
    s = stage()
    s.add("Tetris", 61580)
    plan = s.plan()
    assert plan.status == ("un", "un", "un", "new")
    assert plan.frozen == 3
    assert plan.dirty is True


def test_removing_in_the_middle_rewrites_only_what_follows():
    s = stage()
    s.remove("Chess")
    plan = s.plan()
    # Chess stays visible as "del"; Snake now sits after the divergence, so it is rewritten.
    assert plan.status == ("un", "del", "rw")
    assert (plan.un, plan.rw, plan.nw) == (1, 1, 0)


def test_reordering_walks_the_writable_region_only():
    s = stage()
    s.add("Tetris", 61580)
    s.add("RPN", 69587)
    # Only Tetris and RPN are writable; Periodic/Chess/Snake are frozen and must not move.
    s.move("RPN", -1)
    assert [x.name for x in s.slots] == ["Periodic", "Chess", "Snake", "RPN", "Tetris"]
    assert s.plan().status == ("un", "un", "un", "new", "new")


def test_a_writable_slot_cannot_be_pushed_into_the_frozen_prefix():
    s = stage()
    s.add("Tetris", 61580)
    s.move("Tetris", -1)  # nothing writable above it
    assert [x.name for x in s.slots] == ["Periodic", "Chess", "Snake", "Tetris"]


def test_reordering_past_the_end_is_refused():
    s = stage()
    s.add("Tetris", 61580)
    s.move("Tetris", 1)
    assert [x.name for x in s.slots][-1] == "Tetris"


def test_the_frozen_prefix_cannot_be_reordered():
    s = stage()
    before = [x.name for x in s.slots]
    s.move("Snake", -1)  # everything is frozen: nothing may move
    assert [x.name for x in s.slots] == before


def test_deleted_slots_free_their_bytes():
    s = stage()
    full = s.plan().used_b
    s.remove("Chess")
    assert s.plan().used_b == full - footprint("apps", 135168)


def test_undo_restores_the_previous_arrangement():
    s = stage()
    s.add("Tetris", 61580)
    s.remove("Chess")
    s.undo()
    s.undo()
    assert s.plan().dirty is False
    assert s.can_undo is False


def test_undo_on_a_clean_stage_is_a_no_op():
    s = stage()
    s.undo()
    assert [x.name for x in s.slots] == [d["name"] for d in DEVICE]


def test_reset_drops_every_edit():
    s = stage()
    s.add("Tetris", 61580)
    s.remove("Periodic")
    s.reset()
    assert s.plan().dirty is False
    assert s.can_undo is False


def test_minimize_keeps_only_what_is_already_installed():
    s = stage()
    s.add("Tetris", 61580)
    s.remove("Chess")
    s.minimize()
    assert s.kept_names() == ["Periodic", "Chess", "Snake"]
    assert s.plan().dirty is False


def test_re_adding_a_deleted_slot_rearms_it_in_place():
    s = stage()
    s.remove("Chess")
    assert s.add("Chess", 135168) is True
    assert s.kept_names() == ["Periodic", "Chess", "Snake"]


def test_adding_something_already_staged_is_refused():
    s = stage()
    assert s.add("Chess", 135168) is False


def test_removing_a_staged_but_uninstalled_item_drops_it_entirely():
    s = stage()
    s.add("Tetris", 61580)
    s.remove("Tetris")
    assert [x.name for x in s.slots] == [d["name"] for d in DEVICE]


def test_free_space_never_goes_negative():
    small = Stage("apps", [], 65536)
    small.add("Huge", 10 * APP_SECTOR)
    assert small.plan().free_b == 0


def test_plan_for_is_pure():
    slots = [Slot(name="Periodic", size=61440, on_device=True)]
    first = plan_for("apps", DEVICE, slots, 3145728)
    second = plan_for("apps", DEVICE, slots, 3145728)
    assert first == second


# -- workshop projection ----------------------------------------------------------------
AVAILABLE = [
    {"name": "Tetris", "size": 61580, "source": "github.com/example/games"},
    {"name": "Chess", "size": 135168},
]


def workshop() -> Workshop:
    return Workshop("apps", DEVICE, AVAILABLE, 3145728)


def test_every_row_carries_every_declared_field():
    for row in workshop().device_rows() + workshop().available_rows():
        assert set(row) == set(ROW_FIELDS)


def test_available_rows_flag_what_is_already_staged():
    rows = {r["name"]: r["status"] for r in workshop().available_rows()}
    assert rows == {"Tetris": "free", "Chess": "staged"}


def test_only_the_writable_tail_is_movable():
    w = workshop()
    w.stage.add("Tetris", 61580, w.entry("Tetris"))
    assert {r["name"]: r["movable"] for r in w.device_rows()} == {
        "Periodic": False,
        "Chess": False,
        "Snake": False,
        "Tetris": True,
    }


def test_missing_api_level_is_reported_as_minus_one():
    # QML types the role as int; None would arrive as undefined and blank the row.
    assert workshop().device_rows()[0]["apiLevel"] == -1


def test_segments_cover_only_kept_items():
    w = workshop()
    w.stage.remove("Chess")
    view = w.plan_view()
    assert len(view["segments"]) == 2
    assert all(s["status"] != "del" for s in view["segments"])


def test_plan_view_reports_a_zero_capacity_device_without_dividing_by_zero():
    view = Workshop("apps", [{"name": "X", "size": 10}], [], 0).plan_view()
    assert view["segments"][0]["w"] == 0
    assert view["capText"] == "0 o"


def test_disabled_workshop_is_flagged():
    assert Workshop("scripts", [], [], 0, enabled=False).plan_view()["enabled"] is False


# -- classroom projections --------------------------------------------------------------
ROSTER = {
    "classes": ["3eB", "6eC"],
    "counts": {"3eB": 1, "6eC": 0},
    "total": 2,
    "unfiled_count": 1,
    "calculators": [
        {
            "key": "n0120:aaa",
            "name": "Lab bench",
            "model": "n0120",
            "family": "graphique",
            "class": "3eB",
            "known_firmware": "25.2.0",
            "up_to_date": True,
            "last_scan": (NOW - timedelta(days=3)).isoformat(),
        },
        {
            "key": "n0200:bbb",
            "default": "calc N0200",
            "model": "n0200",
            "family": "scientifique",
            "class": None,
        },
    ],
    "distributions": {
        "3eB": {
            "actions": {"census": True, "firmware": True, "apps": False, "scripts": False},
            "onboarding": "ignore",
            "apps": ["RPN"],
            "scripts": [],
        }
    },
    "dist_apps": ["RPN", "Tetris"],
    "dist_scripts": [],
}


def test_class_filtering():
    assert len(R.roster_rows(ROSTER, R.CLASS_ALL)) == 2
    assert [r["displayName"] for r in R.roster_rows(ROSTER, "3eB")] == ["Lab bench"]
    assert [r["displayName"] for r in R.roster_rows(ROSTER, R.CLASS_UNFILED)] == ["calc N0200"]
    assert R.roster_rows(ROSTER, "6eC") == []


@pytest.mark.parametrize("needle", ["lab", "LAB", " Lab "])
def test_name_filter_is_case_and_space_insensitive(needle):
    assert [r["displayName"] for r in R.roster_rows(ROSTER, R.CLASS_ALL, needle)] == ["Lab bench"]


def test_row_uses_the_default_name_when_unnamed():
    row = R.roster_rows(ROSTER, R.CLASS_UNFILED)[0]
    assert row["displayName"] == "calc N0200"
    assert row["name"] == ""


def test_roster_rows_never_expose_a_role_named_model_or_id():
    # Both are reserved in a QML delegate and would blank every other role.
    for row in R.roster_rows(ROSTER, R.CLASS_ALL):
        assert "model" not in row and "id" not in row
        assert set(row) == set(R.ROSTER_FIELDS)


def test_class_buckets_are_all_then_classes_then_unfiled():
    buckets = R.class_buckets(ROSTER)
    assert [b["classId"] for b in buckets] == [R.CLASS_ALL, "3eB", "6eC", R.CLASS_UNFILED]
    assert [b["count"] for b in buckets] == [2, 1, 0, 1]
    assert set(buckets[0]) == set(R.CLASS_FIELDS)


def test_distribution_of_a_real_class_is_editable():
    view = R.distribution_view(ROSTER, "3eB")
    assert view["editable"] is True
    assert view["onboarding"] == "ignore"
    assert view["apps"] == ["RPN"]
    assert R.enabled_steps(view) == ["census", "firmware"]


@pytest.mark.parametrize("class_id", [R.CLASS_ALL, R.CLASS_UNFILED, ""])
def test_distribution_is_not_editable_outside_a_real_class(class_id):
    view = R.distribution_view(ROSTER, class_id)
    assert view["editable"] is False
    assert view["className"] == ""


def test_unconfigured_class_falls_back_to_the_documented_defaults():
    view = R.distribution_view(ROSTER, "6eC")
    assert view["actions"] == R.default_distribution()["actions"]
    assert R.enabled_steps(view) == ["census", "apps", "scripts"]


def test_distribution_view_offers_the_available_pools():
    view = R.distribution_view(ROSTER, "3eB")
    assert view["availableApps"] == ["RPN", "Tetris"]
    assert view["availableScripts"] == []


def test_projections_tolerate_an_empty_roster():
    assert R.roster_rows({}, R.CLASS_ALL) == []
    assert [b["classId"] for b in R.class_buckets({})] == [R.CLASS_ALL, R.CLASS_UNFILED]
    assert R.distribution_view({}, "3eB")["actions"] == R.default_distribution()["actions"]
