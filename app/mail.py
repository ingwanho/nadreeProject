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
        self.send_message(recipient, "Nadree temporary password",
            "Your temporary Nadree password is:\n\n" + password + "\n\nSign in and change your password.\n")

    def send_deletion_notice(self, recipient, request_id, completed=False):
        stage = "completed in company active systems" if completed else "received"
        self.send_message(recipient, "NadreeGo account deletion request",
            f"The NadreeGo account deletion request affecting your rental access was {stage}.\n"
            f"Request reference: {request_id}\n"
            "Shared information required by another active service follows that service's policy.\n"
            "Contact support using this reference if you need assistance.\n")

    def send_message(self, recipient, subject, body):
        self.check_configuration()
        settings = self.settings
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
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
