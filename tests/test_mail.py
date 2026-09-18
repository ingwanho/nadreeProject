import smtplib

import pytest

from app.config import Settings
from app.errors import Problem
from app.mail import PasswordMailer


@pytest.mark.parametrize("mode", ["starttls", "ssl"])
def test_mail_uses_verified_tls_and_expected_recipient(monkeypatch, mode):
    events = []

    class SMTP:
        def __init__(self, host, port, timeout, **kwargs):
            assert host == "smtp.example.com" and timeout == 10
            if mode == "ssl":
                assert kwargs["context"].check_hostname

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, context):
            assert context.check_hostname
            events.append("tls")

        def login(self, user, password):
            assert user == "mailer" and password == "smtp-test-only"
            events.append("login")

        def send_message(self, message):
            assert message["To"] == "user@example.com"
            assert "temp-password" in message.get_content()
            events.append("sent")
            return {}

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    settings = Settings(_env_file=None, smtp_host="smtp.example.com", smtp_from="noreply@example.com",
                        smtp_user="mailer", smtp_password="smtp-test-only", smtp_tls=mode)
    PasswordMailer(settings).send("user@example.com", "temp-password")
    assert events == (["tls"] if mode == "starttls" else []) + ["login", "sent"]


def test_mail_errors_do_not_expose_server_details(monkeypatch):
    def unavailable(*args, **kwargs):
        raise smtplib.SMTPException("sensitive provider detail")

    monkeypatch.setattr(smtplib, "SMTP", unavailable)
    settings = Settings(_env_file=None, smtp_host="smtp.example.com", smtp_from="noreply@example.com")
    with pytest.raises(Problem) as error:
        PasswordMailer(settings).send("user@example.com", "temp-password")
    assert error.value.code == "MAIL_UNAVAILABLE"
