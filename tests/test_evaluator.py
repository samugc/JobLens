
from joblens_public.core.extraction import extract_skills
from joblens_public.core.real_fit import evaluate_real_fit
from joblens_public.data import load_demo_data


def report_for(candidate_id: str, job_id: str) -> dict:
    candidates, jobs = load_demo_data()
    return evaluate_real_fit(candidates[candidate_id]["bank"], jobs[job_id])


def test_alex_documents_the_ai_requirements_but_not_the_optional_stack():
    report = report_for("alex-rivera", "junior-ai-engineer-aster")
    assert report["required_coverage"] == {
        "documented": 5,
        "total_extracted": 5,
        "ratio": 1.0,
    }
    assert report["preferred_coverage"] == {
        "documented": 0,
        "total_extracted": 2,
        "ratio": 0.0,
    }
    assert report["fit_assessment"]["status"] == "REVIEW_REQUIRED"
    categories = {row["category"] for row in report["manual_review_requirements"]}
    assert {"education", "work_authorization", "production_experience",
            "experience_duration"} <= categories


def test_jordan_documents_the_data_requirements():
    report = report_for("jordan-lee", "data-analyst-harbor")
    assert report["required_coverage"] == {
        "documented": 4,
        "total_extracted": 4,
        "ratio": 1.0,
    }
    assert report["preferred_coverage"]["documented"] == 2
    assert report["preferred_coverage"]["total_extracted"] == 3
    assert report["fit_assessment"]["status"] == "REVIEW_REQUIRED"


def test_switching_candidates_changes_the_evidence_result():
    alex = report_for("alex-rivera", "junior-ai-engineer-aster")
    jordan = report_for("jordan-lee", "junior-ai-engineer-aster")
    assert alex["required_coverage"]["documented"] == 5
    assert jordan["required_coverage"]["documented"] == 2
    assert jordan["fit_assessment"]["status"] == "EVIDENCE_GAPS"


def test_gap_is_explicitly_not_a_disqualification():
    report = report_for("jordan-lee", "junior-ai-engineer-aster")
    gaps = [row for row in report["required"] if row["status"] == "not_documented"]
    assert {row["requirement"] for row in gaps} == {"llm", "nlp", "rag"}
    for row in gaps:
        assert "does not prove lack of ability" in row["basis"]
        assert row["evidence"] == []


def test_report_never_emits_a_hiring_score():
    report = report_for("alex-rivera", "junior-ai-engineer-aster")
    keys = {key.lower() for key in report}
    assert "fit_score" not in keys
    assert "score" not in keys
    assert "probability" not in keys
    assert "ats_score" not in keys


def test_employer_training_and_benefits_are_not_required_skills():
    candidates, _ = load_demo_data()
    description = (
        "Requirements:\n- Python\n- Analyze benefits data with SQL\n\n"
        "Benefits include:\n- We offer training in Docker.\n"
        "- Training in Kubernetes is provided.\n"
    )
    job = {
        "title": "Data Analyst",
        "company": "Synthetic",
        "location": "Remote",
        "description": description,
    }
    report = evaluate_real_fit(candidates["alex-rivera"]["bank"], job)
    required = {row["requirement"] for row in report["required"]}
    preferred = {row["requirement"] for row in report["preferred"]}
    mentioned = {row["requirement"] for row in report["mentioned"]}
    assert required == {"python", "sql"}
    assert preferred == set()
    assert {"docker", "kubernetes"} <= mentioned
    assert extract_skills(description) == (frozenset({"python", "sql"}), frozenset())


def test_location_field_onsite_requirement_triggers_review():
    candidates, jobs = load_demo_data()
    job = dict(jobs["data-analyst-harbor"])
    job["location"] = "Madrid, Spain · On-site"
    job["description"] = "Requirements:\n- Python\n"
    report = evaluate_real_fit(candidates["alex-rivera"]["bank"], job)
    onsite = [
        row for row in report["manual_review_requirements"]
        if row["category"] == "onsite_or_relocation"
    ]
    assert len(onsite) == 1
    assert "on-site" in onsite[0]["trigger"].casefold()


def test_evidence_references_include_exact_claim_text():
    report = report_for("alex-rivera", "junior-ai-engineer-aster")
    references = [
        reference
        for group in ("required", "preferred", "mentioned")
        for item in report[group]
        for reference in item["evidence"]
    ]
    assert references
    for reference in references:
        assert reference["claim"].strip()
    rag = next(item for item in report["required"] if item["requirement"] == "rag")
    assert any(
        "retrieval-augmented" in reference["claim"].casefold()
        for reference in rag["evidence"]
    )
