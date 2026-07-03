"""Strict template renderer + unsubscribe footer/header unit tests (spec §13)."""

from __future__ import annotations

import uuid

import pytest

from app.constants import TEMPLATE_VARIABLES
from app.outreach.renderer import (
    RecipientFacts,
    TemplateRenderError,
    build_context,
    render,
    used_variables,
)
from app.outreach.sender import append_unsubscribe_footer, build_headers


def _full_context() -> dict[str, str]:
    return build_context(
        RecipientFacts(
            first_name="Asha",
            last_name="Patel",
            full_name="Asha Patel",
            company="Acme CA",
            industry="Accounting",
            city="Ahmedabad",
            state="Gujarat",
            country="India",
            services="Audit, Tax Filing",
            designation="Managing Partner",
            website="https://acme.example",
            hiring_signal="Hiring 3 auditors",
        )
    )


def test_all_variables_render():
    ctx = _full_context()
    template = " ".join(f"{{{{{v}}}}}" for v in TEMPLATE_VARIABLES)
    result = render(template, ctx)
    assert "{{" not in result and "}}" not in result
    assert "Asha" in result and "Acme CA" in result and "Ahmedabad" in result


def test_unknown_variable_rejected():
    with pytest.raises(TemplateRenderError) as exc:
        render("Hi {{Nickname}}", {"Nickname": "x"})
    assert "Unknown" in str(exc.value)


def test_missing_value_rejected_not_literal():
    """A known var with no value must FAIL, never ship a literal {{X}}."""
    ctx = build_context(RecipientFacts(first_name=None, company="Acme"))
    with pytest.raises(TemplateRenderError):
        render("Hi {{FirstName}} at {{Company}}", ctx)


def test_whitespace_only_value_rejected():
    with pytest.raises(TemplateRenderError):
        render("Hi {{FirstName}}", {"FirstName": "   "})


def test_used_variables_dedup_and_order():
    assert used_variables("{{A}} {{B}} {{A}}") == ["A", "B"]


def test_full_name_derived_from_first_last():
    ctx = build_context(RecipientFacts(first_name="Sam", last_name="Rao"))
    assert render("{{FullName}}", ctx) == "Sam Rao"


def test_render_preserves_surrounding_text():
    ctx = build_context(RecipientFacts(first_name="Kim", company="Beta"))
    out = render("Dear {{FirstName}}, about {{Company}}.", ctx)
    assert out == "Dear Kim, about Beta."


def test_whitespace_in_braces_tolerated():
    ctx = build_context(RecipientFacts(first_name="Lee"))
    assert render("{{ FirstName }}", ctx) == "Lee"


# ---- unsubscribe footer + headers ----------------------------------------- #


def test_unsubscribe_footer_appended():
    body = "Hello there."
    out = append_unsubscribe_footer(body, "Reply STOP to opt out.")
    assert "Reply STOP to opt out." in out
    assert out.startswith("Hello there.")
    assert "-- " in out  # signature separator


def test_unsubscribe_footer_not_duplicated():
    text = "Reply STOP to opt out."
    body = f"Hello.\n\n-- \n{text}"
    out = append_unsubscribe_footer(body, text)
    assert out.count(text) == 1


def test_list_unsubscribe_header_and_message_id():
    mid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    headers = build_headers(mid, "sender@leadmine.local", "Reply STOP.")
    assert headers["Message-ID"].startswith(f"<lm-{mid}@")
    assert headers["Message-ID"].endswith(">")
    assert headers["X-LeadMine-Id"] == str(mid)
    assert "List-Unsubscribe" in headers
    assert "mailto:sender@leadmine.local" in headers["List-Unsubscribe"]
