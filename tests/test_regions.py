"""Generic write planner: prefix untouched, suffix rewritten. Pure, offline."""

from nwupdater.regions import PlanItem, plan

SEC = 64 * 1024
CAP = 61 * SEC


def _apps(ids, size=SEC):
    return [PlanItem(c, size) for c in ids]


def test_append_leaves_prefix_untouched():
    p = plan(_apps("ABC"), _apps("ABCD"), capacity=CAP, sector=SEC)
    assert p.first_changed == 3 and p.rewrite == ["D"] and p.write_bytes == SEC


def test_middle_delete_rewrites_suffix():
    p = plan(_apps("ABCDE"), _apps("ABDE"), capacity=CAP, sector=SEC)
    assert p.first_changed == 2 and p.rewrite == ["D", "E"]


def test_delete_first_rewrites_everything():
    p = plan(_apps("ABC"), _apps("BC"), capacity=CAP, sector=SEC)
    assert p.first_changed == 0 and p.rewrite == ["B", "C"]


def test_no_change_writes_nothing():
    p = plan(_apps("ABC"), _apps("ABC"), capacity=CAP, sector=SEC)
    assert p.first_changed == 3 and p.rewrite == [] and p.write_bytes == 0 and p.erase_bytes == 0


def test_capacity_overflow_flagged():
    assert plan([], _apps("ABC"), capacity=2 * SEC, sector=SEC).fits is False
    assert plan([], _apps("AB"), capacity=2 * SEC, sector=SEC).fits is True


def test_packed_sram_has_no_erase():
    cur = [PlanItem("a", 100)]
    tgt = [PlanItem("a", 100), PlanItem("b", 50)]
    p = plan(cur, tgt, capacity=42 * 1024, sector=None)
    assert p.erase_bytes == 0 and p.write_bytes == 50 and p.first_changed == 1
