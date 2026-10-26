"""Precise errors without weakening receipt or content validation."""

import copy

import pytest

from joblens_public.cv import CvDraft, CvDraftItem, CvDraftSection
from joblens_public.release_guard import ReviewGuard, ReviewValidationError


def draft(guard):
    value = guard.issue_draft(
        CvDraft(
            sections=(
                CvDraftSection("skills", "skills", "Skills", (CvDraftItem("i", "Python", ("f",)),)),
            )
        )
    )
    value["review"]["baseline"]["review_mode"] = "provisional"
    value["review"]["receipt"] = guard.sign("baseline", value["review"]["baseline"])
    return value


@pytest.mark.parametrize("name", [None, "", "   "])
def test_missing_name_is_actionable(name):
    guard = ReviewGuard()
    value = draft(guard)
    value["candidate"]["full_name"] = name
    with pytest.raises(ReviewValidationError) as error:
        guard.confirm_all(value, True, True)
    assert error.value.code == "missing_contact"
    assert not value["review"]["approvals"]


def test_session_invalid_token_and_changed_content_are_distinct():
    guard = ReviewGuard()
    value = draft(guard)
    value["candidate"]["full_name"] = "Alex Example"
    with pytest.raises(ReviewValidationError) as error:
        ReviewGuard().confirm_all(value, True, True)
    assert error.value.code == "session_expired"
    forged = copy.deepcopy(value)
    forged["review"]["receipt"] = "forged"
    with pytest.raises(ReviewValidationError) as error:
        guard.confirm_all(forged, True, True)
    assert error.value.code == "invalid_request"
    confirmed = guard.confirm_all(value, True, True)
    confirmed["sections"][0]["items"][0]["text"] = "Edited wording"
    with pytest.raises(ReviewValidationError) as error:
        guard.export(confirmed, True, confirmed["candidate"])
    assert error.value.code == "draft_changed"
