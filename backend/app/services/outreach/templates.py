"""HIPAA + TCPA safe outreach templates.

Rule: SMS and voice channels MUST NEVER include a diagnosis name —
just generic prompts to schedule. Email and letter may carry more
detail because they sit behind authenticated mailboxes / addressed
delivery, but still avoid stigmatizing language.
"""
from __future__ import annotations

from typing import TypedDict

# Stigmatizing / diagnosis terms banned from SMS + voice
BANNED_IN_SMS_VOICE = {
    "diabetes", "cancer", "depression", "hiv", "schizophrenia",
    "bipolar", "stroke", "renal failure", "ckd", "copd", "chf",
}


class TemplatePack(TypedDict):
    sms: str
    voice: str
    email_subject: str
    email_html: str
    letter_html: str


def _opt_out_footer_sms() -> str:
    return " Reply STOP to opt out."


_TEMPLATES_EN: dict[str, TemplatePack] = {
    "AWV": {
        "sms": (
            "Hi {first_name}, it's time for your annual wellness visit at "
            "{clinic}. Call {phone} to schedule."
        ),
        "voice": (
            "Hello {first_name}. This is a reminder from {clinic} that you "
            "are due for your annual wellness visit. Please call us at "
            "{phone} to schedule. Thank you."
        ),
        "email_subject": "Time for your annual wellness visit",
        "email_html": (
            "<p>Hi {first_name},</p>"
            "<p>Our records show it's time for your annual wellness visit. "
            "Wellness visits are covered at no cost under Medicare Advantage "
            "and help us catch issues early.</p>"
            "<p><a href=\"{schedule_url}\">Schedule online</a> "
            "or call {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
        ),
        "letter_html": (
            "<p>Dear {first_name},</p>"
            "<p>Our records indicate you are due for your annual wellness "
            "visit. Please call {phone} to schedule a convenient time.</p>"
            "<p>Sincerely,<br/>{clinic}</p>"
        ),
    },
    "BCS": {
        "sms": (
            "Hi {first_name}, it's time for your routine screening at "
            "{clinic}. Call {phone}."
        ),
        "voice": (
            "Hello {first_name}. This is a reminder from {clinic} about a "
            "preventive screening you are due for. Please call {phone}. "
            "Thank you."
        ),
        "email_subject": "Time for your breast cancer screening",
        "email_html": (
            "<p>Hi {first_name},</p>"
            "<p>You are due for your routine mammogram. Early detection "
            "saves lives.</p>"
            "<p><a href=\"{schedule_url}\">Schedule online</a> "
            "or call {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
        ),
        "letter_html": (
            "<p>Dear {first_name},</p>"
            "<p>You are due for a routine mammogram. Please call {phone} "
            "to schedule.</p>"
            "<p>{clinic}</p>"
        ),
    },
    "CCS": {
        "sms": (
            "Hi {first_name}, you have a preventive screening due at "
            "{clinic}. Call {phone}."
        ),
        "voice": (
            "Hello {first_name}. This is {clinic}. You have a preventive "
            "screening due. Please call {phone}."
        ),
        "email_subject": "Time for your cervical cancer screening",
        "email_html": (
            "<p>Hi {first_name},</p>"
            "<p>You are due for your routine cervical cancer screening "
            "(Pap or HPV test).</p>"
            "<p><a href=\"{schedule_url}\">Schedule online</a> "
            "or call {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
        ),
        "letter_html": (
            "<p>Dear {first_name},</p>"
            "<p>You are due for a routine cervical cancer screening. "
            "Please call {phone}.</p>"
            "<p>{clinic}</p>"
        ),
    },
    "HBD": {
        "sms": (
            "Hi {first_name}, you have a routine lab follow-up due at "
            "{clinic}. Call {phone}."
        ),
        "voice": (
            "Hello {first_name}. This is {clinic}. You have a routine "
            "lab follow-up due. Please call {phone}."
        ),
        "email_subject": "Time for your diabetes follow-up labs",
        "email_html": (
            "<p>Hi {first_name},</p>"
            "<p>You are due for your routine A1c check. Keeping this on "
            "schedule helps us manage your diabetes care.</p>"
            "<p><a href=\"{schedule_url}\">Schedule labs</a> "
            "or call {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
        ),
        "letter_html": (
            "<p>Dear {first_name},</p>"
            "<p>You are due for routine diabetes follow-up labs. Please "
            "call {phone}.</p>"
            "<p>{clinic}</p>"
        ),
    },
    "CBP": {
        "sms": (
            "Hi {first_name}, a routine BP recheck is due at {clinic}. "
            "Call {phone}."
        ),
        "voice": (
            "Hello {first_name}. This is {clinic}. You have a routine "
            "follow-up due. Please call {phone}."
        ),
        "email_subject": "Time for your blood pressure follow-up",
        "email_html": (
            "<p>Hi {first_name},</p>"
            "<p>You are due for a routine blood pressure check.</p>"
            "<p><a href=\"{schedule_url}\">Schedule online</a> "
            "or call {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
        ),
        "letter_html": (
            "<p>Dear {first_name},</p>"
            "<p>You are due for a routine blood pressure check. Please "
            "call {phone}.</p>"
            "<p>{clinic}</p>"
        ),
    },
    "FUM": {
        "sms": (
            "Hi {first_name}, please call {clinic} at {phone} to schedule "
            "a follow-up appointment."
        ),
        "voice": (
            "Hello {first_name}. This is {clinic}. Please call us at "
            "{phone} to schedule a follow-up. Thank you."
        ),
        "email_subject": "Let's schedule your follow-up",
        "email_html": (
            "<p>Hi {first_name},</p>"
            "<p>We'd like to schedule a follow-up appointment to check "
            "in on how you're doing.</p>"
            "<p><a href=\"{schedule_url}\">Schedule online</a> "
            "or call {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Unsubscribe</a></p>"
        ),
        "letter_html": (
            "<p>Dear {first_name},</p>"
            "<p>We'd like to schedule a follow-up appointment. Please "
            "call {phone}.</p>"
            "<p>{clinic}</p>"
        ),
    },
}

# Spanish — same shapes, same rules
_TEMPLATES_ES: dict[str, TemplatePack] = {
    "AWV": {
        "sms": (
            "Hola {first_name}, es momento de su visita de bienestar "
            "anual en {clinic}. Llame al {phone}."
        ),
        "voice": (
            "Hola {first_name}. Llamamos de {clinic}. Su visita de "
            "bienestar anual está pendiente. Llame al {phone}. Gracias."
        ),
        "email_subject": "Hora de su visita de bienestar anual",
        "email_html": (
            "<p>Hola {first_name},</p>"
            "<p>Es hora de su visita de bienestar anual.</p>"
            "<p><a href=\"{schedule_url}\">Agendar en línea</a> o llame "
            "al {phone}.</p>"
            "<p style=\"font-size:11px;color:#64748b\">"
            "<a href=\"{unsubscribe_url}\">Cancelar suscripción</a></p>"
        ),
        "letter_html": (
            "<p>Estimado/a {first_name},</p>"
            "<p>Su visita de bienestar anual está pendiente. Llame al "
            "{phone}.</p><p>{clinic}</p>"
        ),
    },
    # (other measures fall back to English when ES not defined)
}


def get_template(measure_id: str, channel: str, language: str = "en") -> str:
    """Return the rendered template string (pre-substitution).

    For SMS/voice, appends opt-out footer.
    """
    packs = _TEMPLATES_ES if language == "es" else _TEMPLATES_EN
    pack = packs.get(measure_id) or _TEMPLATES_EN.get(measure_id)
    if not pack:
        raise ValueError(f"No template for measure_id={measure_id}")
    if channel == "sms":
        return pack["sms"] + _opt_out_footer_sms()
    if channel == "voice":
        return pack["voice"]
    if channel == "email":
        return pack["email_html"]
    if channel == "letter":
        return pack["letter_html"]
    raise ValueError(f"Unknown channel: {channel}")


def get_email_subject(measure_id: str, language: str = "en") -> str:
    packs = _TEMPLATES_ES if language == "es" else _TEMPLATES_EN
    pack = packs.get(measure_id) or _TEMPLATES_EN.get(measure_id)
    if not pack:
        raise ValueError(f"No template for measure_id={measure_id}")
    return pack["email_subject"]


def render(template_str: str, **fields: str) -> str:
    return template_str.format(**fields)


def template_is_phi_safe(measure_id: str, channel: str) -> bool:
    """SMS + voice templates must not name a diagnosis. Asserted in tests."""
    if channel not in {"sms", "voice"}:
        return True
    body = (get_template(measure_id, channel) or "").lower()
    return not any(word in body for word in BANNED_IN_SMS_VOICE)
