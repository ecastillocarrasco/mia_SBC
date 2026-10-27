"""Firma corporativa de correo. Los datos variables se resuelven para el usuario autenticado."""

from __future__ import annotations

import html
from dataclasses import dataclass

SIGNATURE_BANNER_CID = "mia-sbc-signature-banner"
COMMON_CONTACT_LINE = "+34 952 579400 Ext.7702 | sunsetbeachclub.com"

_PRIVACY_ES = (
    "Este mensaje y sus archivos adjuntos van dirigidos exclusivamente a su destinatario, pudiendo contener "
    "información confidencial sometida a secreto profesional. No está permitida su reproducción o distribución "
    "sin la autorización expresa de SUNSET BEACH CLUB S.A. Si usted no es el destinatario final por favor "
    "elimínelo e infórmenos por esta vía.\n\n"
    "De acuerdo con lo establecido por legislación vigente en materia de Protección de Datos de Carácter "
    "Personal, le informamos que sus datos están incorporados en un fichero del que es titular SUNSET BEACH "
    "CLUB S.A. con la finalidad de realizar la gestión administrativa, contable y fiscal, así como enviarle "
    "comunicaciones comerciales sobre nuestros productos y/o servicios en caso de que nos haya dado su "
    "consentimiento.\n\n"
    "Asimismo, le informamos de la posibilidad de ejercer los derechos de acceso, rectificación, cancelación y "
    "resto sobre sus datos en el domicilio de SUNSET BEACH CLUB S.A. sito en AVENIDA DEL SOL, 5 - 29630 - "
    "BENALMADENA COSTA - MÁLAGA.\n\n"
    "Si usted no desea recibir nuestra información, póngase en contacto con nosotros enviando un correo "
    "electrónico a la siguiente dirección: info@sunsetbeachclub.com\n\n"
    "Le informamos que puede asimismo contactar con nuestro delegado de protección de datos D. Ernest Abelló, "
    "dirigiéndose a https://sunsetbeachclub-canaletico.appcore.es/"
)
_EQUALITY_ES = (
    "Desde Sunset Beach Club mostramos nuestro más firme compromiso con la sociedad y con nuestra organización "
    "en el cumplimiento de la normativa vigente en materia de igualdad y de lucha contra la discriminación "
    "entre mujeres y hombres. A tales efectos, nos complace poner en su conocimiento que, en estricta aplicación "
    "de la Ley Orgánica 3/2007, de 22 de marzo para la igualdad efectiva de mujeres y hombres y del Real Decreto "
    "901/2020, de 13 de octubre, se ha procedido a elaborar y registrar el Plan de Igualdad de esta empresa "
    "(Núm.Reg. REGCON 29100782112022), cuyas medidas para garantizar la efectividad de la igualdad y la no "
    "discriminación entre hombres y mujeres, se hacen extensibles a nuestro equipo humano así como a nuestras "
    "relaciones comerciales y profesionales."
)
_PRIVACY_EN = (
    "This message and its attachments are addressed exclusively to the recipient and may contain confidential "
    "information subject to professional secrecy. It is not allowed to reproduce or distribute it without the "
    "express authorization of SUNSET BEACH CLUB S.A. If you are not the final recipient, please delete it and "
    "inform us in this way.\n\n"
    "In accordance with the current legislation of Personal Data, we inform you that your personal information "
    "is included in a file owned by SUNSET BEACH CLUB S.A. with the purpose of carrying out administrative, "
    "accounting and fiscal management, as well as sending you commercial communications about our products and / "
    "or services in case you have given us your consent.\n\n"
    "Likewise, we inform you of the possibility of exercising rights of access, rectification, cancellation and "
    "rest on your data at the address of SUNSET BEACH CLUB S.A. located in AVENIDA DEL SOL, 5 - 29630 - "
    "BENALMADENA COSTA - MÁLAGA - SPAIN.\n\n"
    "If you do not wish to receive our information, please contact us by sending an email to the following "
    "address: info@sunsetbeachclub.com\n\n"
    "We inform you that you can also contact our data protection officer Mr. Ernest Abelló, by "
    "https://sunsetbeachclub-canaletico.appcore.es/"
)


@dataclass(frozen=True, slots=True)
class MailSignature:
    html: str
    preview: str
    display_name: str
    position_es: str | None
    position_en: str | None
    phone: str | None


def _line_breaks(value: str) -> str:
    return html.escape(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def build_mail_signature(display_name: str, position: str | None, phone: str | None) -> MailSignature:
    """Genera una firma segura para HTML y una vista previa textual.

    ``Employee.position`` puede contener una equivalencia bilingüe separada por ``/``. Si aún no
    existe, se muestra solo el puesto en español; no se inventa su traducción.
    """
    name = display_name.strip()
    role_es: str | None = None
    role_en: str | None = None
    if position and position.strip():
        parts = [part.strip() for part in position.split("/", maxsplit=1)]
        role_es = parts[0] or None
        role_en = parts[1] or None if len(parts) == 2 else None
    contact_phone = phone.strip() if phone and phone.strip() else None

    identity = [
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:700;color:#00a0b5">{html.escape(name)}</div>'
    ]
    if role_es:
        title = html.escape(role_es)
        if role_en:
            title += f" / {html.escape(role_en)}"
        identity.append(
            f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#0b2f55">{title}</div>'
        )
    if contact_phone:
        identity.append(
            f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#0b2f55">{html.escape(contact_phone)}</div>'
        )
    identity.append(
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#0b2f55">'
        '<a href="tel:+34952579400" style="color:#0b2f55;text-decoration:none">+34 952 579400 Ext.7702</a>'
        ' &nbsp;|&nbsp; <a href="https://sunsetbeachclub.com" style="color:#00a0b5;text-decoration:none">sunsetbeachclub.com</a>'
        "</div>"
    )
    identity.append(
        f'<div style="margin:10px 0"><img src="cid:{SIGNATURE_BANNER_CID}" '
        'alt="Amazing Holidays all year round · ¡Vacaciones increíbles todo el año!" '
        'width="600" style="display:block;width:100%;max-width:600px;height:auto;border:0"></div>'
    )
    legal = (
        ("Cláusula de Privacidad", _PRIVACY_ES),
        ("Cláusula de Igualdad", _EQUALITY_ES),
        ("Privacy Clause", _PRIVACY_EN),
    )
    legal_html = "".join(
        '<p style="margin:8px 0 3px;font-weight:700">'
        f'{html.escape(heading)}</p><p style="margin:0 0 9px">{_line_breaks(body)}</p>'
        for heading, body in legal
    )
    signature_html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#27364b;font-size:11px;line-height:1.45">'
        f"{''.join(identity)}"
        '<div style="margin-top:12px;border-top:1px solid #d9e0e8;padding-top:7px;color:#657386;font-size:9px">'
        f"{legal_html}</div></div>"
    )
    preview_lines = [name]
    if role_es:
        preview_lines.append(f"{role_es}{f' / {role_en}' if role_en else ''}")
    if contact_phone:
        preview_lines.append(contact_phone)
    preview_lines.extend(
        (
            COMMON_CONTACT_LINE,
            "[Banda gráfica Sunset Beach Club]",
            "",
            "Cláusula de Privacidad.",
            _PRIVACY_ES,
            "",
            "Cláusula de Igualdad.",
            _EQUALITY_ES,
            "",
            "Privacy Clause",
            _PRIVACY_EN,
        )
    )
    return MailSignature(
        html=signature_html,
        preview="\n".join(preview_lines),
        display_name=name,
        position_es=role_es,
        position_en=role_en,
        phone=contact_phone,
    )
