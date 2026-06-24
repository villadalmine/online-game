"""i18n de los mensajes de error del server (SDD 4).

Mapa ES→EN de los `detail` ESTÁTICos más comunes (auth/seguridad/combate). Se traduce en un
exception handler global cuando el request pide `en`. Los mensajes dinámicos (con valores
interpolados: recursos/atmósfera/agua) pasan tal cual — follow-up: pasarlos a claves+params.
"""
ERR_EN: dict[str, str] = {
    "Email inválido.": "Invalid email.",
    "Registro por invitación: email requerido.": "Invite-only: email required.",
    "Ese email no está autorizado.": "That email is not authorized.",
    "El usuario ya existe": "Username already exists.",
    "Ese email ya tiene cuenta.": "That email already has an account.",
    "Credenciales invalidas": "Invalid credentials.",
    "Token invalido": "Invalid token.",
    "Jugador no encontrado": "Player not found.",
    "Solo el admin puede hacer esto.": "Admins only.",
    "Demasiados intentos; esperá un momento.": "Too many attempts; wait a moment.",
    "Demasiadas consultas al asistente; espera un momento.":
        "Too many assistant requests; wait a moment.",
    "Demasiados ataques; espera un momento.": "Too many attacks; wait a moment.",
    "Código inválido o expirado.": "Invalid or expired code.",
    "Ese jugador está bajo protección de novato.": "That player is under newbie protection.",
    "Ese jugador está en otra galaxia.": "That player is in another galaxy.",
    "Primero completa el onboarding.": "Complete onboarding first.",
}


def translate(detail: str, lang: str) -> str:
    if lang == "en":
        return ERR_EN.get(detail, detail)
    return detail
