"""The mail the hosted app sends, in the reader's language: confirming an address, resetting a
password, and what follows a copyright notice (see copyright.py). Without an SMTP server
configured, a message is written to the log instead."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from . import config

log = logging.getLogger(__name__)

TEXTS = {
    "verify": {
        "en": ("Confirm your email",
               "Open this link to confirm your email and start using your account:\n\n{link}\n\n"
               "It works for 48 hours. If you didn't sign up, ignore this message."),
        "es": ("Confirma tu correo",
               "Abre este enlace para confirmar tu correo y empezar a usar tu cuenta:\n\n{link}\n\n"
               "Funciona durante 48 horas. Si no te registraste, ignora este mensaje."),
    },
    "exists": {
        "en": ("You already have an account",
               "Someone tried to sign up with this email, but it already has an account. If it was you, "
               "sign in, or choose a new password here:\n\n{link}\n\nIf it wasn't you, ignore this message."),
        "es": ("Ya tienes una cuenta",
               "Alguien intentó registrarse con este correo, pero ya tiene una cuenta. Si fuiste tú, inicia "
               "sesión o elige una contraseña nueva aquí:\n\n{link}\n\nSi no fuiste tú, ignora este mensaje."),
    },
    "reset": {
        "en": ("Choose a new password",
               "Open this link to choose a new password:\n\n{link}\n\n"
               "It works for one hour. If you didn't ask for it, ignore this message: your password stays the same."),
        "es": ("Elige una contraseña nueva",
               "Abre este enlace para elegir una contraseña nueva:\n\n{link}\n\n"
               "Funciona durante una hora. Si no lo pediste, ignora este mensaje: tu contraseña no cambia."),
    },
    # To the owner of a book disabled after a copyright notice.
    "takedown": {
        "en": ("A book in your library was disabled",
               "After a copyright notice, “{title}” was disabled in your library on {date}. You can't open it any more.\n\n"
               "The notice was sent on behalf of {claimant}, about this work:\n{work}\n\n"
               "If you think this is a mistake, or that you have the right to use the book, you can send a "
               "counter-notice within {days} days:\n\n{link}\n\n"
               "If you don't, the book will be deleted after that time. This is strike {strikes} of {limit} on your "
               "account: at {limit}, the account is closed."),
        "es": ("Se deshabilitó un libro de tu biblioteca",
               "Tras un aviso de derechos de autor, «{title}» se deshabilitó en tu biblioteca el {date}. Ya no puedes abrirlo.\n\n"
               "El aviso se envió en nombre de {claimant}, sobre esta obra:\n{work}\n\n"
               "Si crees que es un error, o que tienes derecho a usar el libro, puedes enviar un contraaviso "
               "en un plazo de {days} días:\n\n{link}\n\n"
               "Si no lo haces, el libro se eliminará pasado ese plazo. Es la amonestación {strikes} de {limit} de tu "
               "cuenta: con {limit}, la cuenta se cierra."),
    },
    "restored": {
        "en": ("Your book is available again",
               "“{title}” is available in your library again, and the strike it had brought is withdrawn."),
        "es": ("Tu libro está disponible de nuevo",
               "«{title}» vuelve a estar disponible en tu biblioteca, y se retiró la amonestación que había generado."),
    },
    "closed": {
        "en": ("Your account was closed",
               "Your account was closed because it reached {limit} strikes for copyright notices (our policy on repeat "
               "infringement). You can't sign in any more.\n\n"
               "Your library will be deleted after {days} days. If you think this is a mistake, answer this message before then."),
        "es": ("Tu cuenta se cerró",
               "Tu cuenta se cerró porque llegó a {limit} amonestaciones por avisos de derechos de autor (nuestra política "
               "sobre infracciones reiteradas). Ya no puedes iniciar sesión.\n\n"
               "Tu biblioteca se eliminará dentro de {days} días. Si crees que es un error, responde a este mensaje antes."),
    },
    "closed_other": {
        "en": ("Your account was closed",
               "Your account was closed: {reason}\n\nYou can't sign in any more. Your library will be deleted after "
               "{days} days. If you think this is a mistake, answer this message before then."),
        "es": ("Tu cuenta se cerró",
               "Tu cuenta se cerró: {reason}\n\nYa no puedes iniciar sesión. Tu biblioteca se eliminará dentro de "
               "{days} días. Si crees que es un error, responde a este mensaje antes."),
    },
    # To whoever sent a notice that won't be acted on.
    "rejected": {
        "en": ("Your copyright notice #{notice}",
               "You sent us a copyright notice (#{notice}) about this work:\n{work}\n\n"
               "We can't act on it: {why}\n\nIf you can fill in what is missing, send a new notice:\n\n{link}"),
        "es": ("Tu aviso de derechos de autor n.º {notice}",
               "Nos enviaste un aviso de derechos de autor (n.º {notice}) sobre esta obra:\n{work}\n\n"
               "No podemos atenderlo: {why}\n\nSi puedes completar lo que falta, envía un aviso nuevo:\n\n{link}"),
    },
    # To whoever sent a notice: the counter-notice its uploader sent.
    "forwarded": {
        "en": ("Counter-notice to your notice #{notice}",
               "You sent us a copyright notice (#{notice}) about this work:\n{work}\n\n"
               "The owner of an upload it named sent this counter-notice:\n\n{text}\n\n"
               "Unless, within {wait} business days, you answer this message showing that you have started a court or "
               "administrative action, filed a criminal complaint, or started mediation or arbitration about it, we will "
               "make the material available to them again."),
        "es": ("Contraaviso a tu aviso n.º {notice}",
               "Nos enviaste un aviso de derechos de autor (n.º {notice}) sobre esta obra:\n{work}\n\n"
               "Quien subió uno de los archivos que señalaba envió este contraaviso:\n\n{text}\n\n"
               "Salvo que en un plazo de {wait} días hábiles respondas a este mensaje acreditando que iniciaste un "
               "procedimiento judicial o administrativo, presentaste una denuncia penal o iniciaste un mecanismo alterno "
               "de solución de controversias al respecto, volveremos a poner el material a su disposición."),
    },
    # To the site's copyright agent, as notices and counter-notices arrive.
    "notice": {
        "en": ("Copyright notice #{id}",
               "A copyright notice arrived:\n\n{text}\n\nTo act on it: python scripts/admin.py notice {id}"),
    },
    "counter": {
        "en": ("Counter-notice #{id}",
               "The owner of a disabled book sent a counter-notice:\n\n{text}\n\n"
               "To send it on to whoever sent the notice: python scripts/admin.py forward {id}"),
    },
}


def send(to: str, kind: str, lang: str, reply_to: str | None = None, **fields) -> None:
    """Sends a message of ``kind`` (a key of TEXTS), its blanks filled with ``fields``."""
    subject, body = TEXTS[kind].get(lang, TEXTS[kind]["en"])
    subject = subject.format(**fields)
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = f"{subject} · Chess Books Visualizer"
    msg.set_content(body.format(**fields))
    if not config.SMTP_HOST:
        log.warning("no CBV_SMTP_HOST, so this mail was not sent:\nTo: %s\nSubject: %s\n\n%s", to, subject, msg.get_content())
        return
    secure = config.SMTP_PORT == 465
    with (smtplib.SMTP_SSL if secure else smtplib.SMTP)(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
        if not secure:
            smtp.starttls()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
        smtp.send_message(msg)
