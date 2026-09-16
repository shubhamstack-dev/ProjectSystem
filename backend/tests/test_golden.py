"""golden.json was produced by the original browser implementation, whose engine
was verified against hand-checked forward/backward passes. These tests assert the
Python port reproduces it exactly: same working-day indices, same calendar
dates, same float, same critical path. If one fails, the port has drifted."""
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scheduling.engine import AUTO, MANUAL, schedule, wbs_of  # noqa: E402
from app.scheduling.work_calendar import WorkCalendar  # noqa: E402

TYPES = {"FS": 0, "SS": 1, "FF": 2, "SF": 3}


@dataclass
class Dep:
    predecessor_id: int
    type: int
    lag: int


@dataclass
class Act:
    id: int
    level: int
    name: str
    duration: int
    mode: int
    planned_start: date | None = None
    planned_finish: date | None = None
    percent_complete: int = 0
    dependencies: list = field(default_factory=list)


def build():
    g = json.loads((Path(__file__).parent / "golden.json").read_text())
    cal = WorkCalendar(date.fromisoformat(g["start"]), [date.fromisoformat(h) for h in g["holidays"]])
    acts = []
    for i, r in enumerate(g["rows"]):
        manual = r["mode"] == "manual"
        acts.append(Act(
            id=i + 1, level=r["level"], name=r["name"], duration=r["duration"],
            mode=MANUAL if manual else AUTO,
            planned_start=date.fromisoformat(r["startDate"]) if manual else None,
            planned_finish=date.fromisoformat(r["finishDate"]) if manual else None,
        ))
    wbs_map = {wbs_of(acts, i): a for i, a in enumerate(acts)}
    for i, r in enumerate(g["rows"]):
        for token in [t.strip() for t in r["pred"].split(",") if t.strip()]:
            m = re.match(r"^(\d+(?:\.\d+)*)\s*(FS|SS|FF|SF)?\s*([+-]\d+)?$", token.upper())
            assert m, token
            pred = wbs_map[m.group(1)]
            acts[i].dependencies.append(Dep(pred.id, TYPES[m.group(2) or "FS"], int(m.group(3) or 0)))
    return acts, cal, g


def test_engine_matches_golden():
    acts, cal, g = build()
    result = schedule(acts, cal)
    assert not result.has_cycle
    assert result.project_end == g["projectEnd"]
    assert result.project_end_date.isoformat() == g["projectEndDate"]
    for a, r in zip(acts, g["rows"]):
        assert a.wbs == r["wbs"], a.name
        assert a.is_summary == r["summary"], a.name
        assert a.duration == r["duration"], a.name
        assert a.computed_start == r["start"], a.name
        assert a.computed_finish == r["finish"], a.name
        assert a.computed_start_date.isoformat() == r["startDate"], a.name
        assert a.computed_finish_date.isoformat() == r["finishDate"], a.name
        if not a.is_summary:
            assert a.total_float == r["float"], a.name
            assert a.is_critical == r["critical"], a.name


if __name__ == "__main__":
    test_engine_matches_golden()
    print("golden test passed")
