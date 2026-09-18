import smtplib
import ssl
from email.message import EmailMessage

from app.errors import Problem


class PasswordMailer:
    def __init__(self, settings):
        self.settings = settings

    def check_configuration(self):
        if not self.settings.smtp_host or not self.settings.smtp_from:
            raise Problem(503, "MAIL_NOT_CONFIGURED")

    def send(self, recipient, password):
        self.check_configuration()
        settings = self.settings
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = "Nadree temporary password"
        message.set_content("Your temporary Nadree password is:\n\n" + password +
                            "\n\nSign in and change your password.\n")
        try:
            context = ssl.create_default_context()
            if settings.smtp_tls == "ssl":
                client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
            else:
                client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            with client:
                if settings.smtp_tls == "starttls":
                    client.starttls(context=context)
                if settings.smtp_user:
                    client.login(settings.smtp_user, settings.smtp_password.get_secret_value())
                if client.send_message(message):
                    raise Problem(503, "MAIL_UNAVAILABLE")
        except (smtplib.SMTPException, OSError, ValueError):
            raise Problem(503, "MAIL_UNAVAILABLE") from None
