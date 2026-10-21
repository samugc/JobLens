import json

from joblens_public.data import load_demo_data


def test_demo_data_is_complete_and_synthetic():
    candidates, jobs = load_demo_data()
    assert set(candidates) == {"alex-rivera", "jordan-lee"}
    assert len(jobs) == 3
    for candidate in candidates.values():
        assert "Fictional candidate" in candidate["note"]
        assert candidate["bank"]["candidate"]["id"] == candidate["id"]
        for fact in candidate["bank"]["facts"]:
            assert fact["attested_by_user"] is True
            assert fact["source"].startswith("synthetic/")
    for job in jobs.values():
        assert job["synthetic"] is True
        assert job["description"].strip()


def test_candidate_banks_are_not_identical():
    candidates, _ = load_demo_data()
    alex = json.dumps(candidates["alex-rivera"]["bank"], sort_keys=True)
    jordan = json.dumps(candidates["jordan-lee"]["bank"], sort_keys=True)
    assert alex != jordan
