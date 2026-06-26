"""TTS de servidor (SDD 43, modo "jugar sin leer").

Para navegadores SIN voces instaladas (típico Chromium/Linux) el `speechSynthesis` del front no
suena. Este endpoint sintetiza el texto con **espeak-ng** y devuelve un WAV que el cliente reproduce
por el mismo canal de audio que sus beeps. Es un fallback: si el navegador ya tiene voces, el front
ni lo llama.

Seguridad: el texto se acota y se pasa por **stdin** a un proceso sin shell (sin inyección). No
requiere auth (igual que el catálogo): solo lee etiquetas cortas del juego.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Query, Response, status

router = APIRouter()

_MAX_CHARS = 600


@router.get("/tts")
async def tts(
    text: str = Query(..., description="texto a leer (acotado)"),
    lang: str = Query("es", description="es|en"),
):
    text = (text or "").strip()[:_MAX_CHARS]
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "texto vacío")
    voice = "en-us" if lang.lower().startswith("en") else "es-419"
    try:
        proc = await asyncio.create_subprocess_exec(
            "espeak-ng", "-v", voice, "-s", "160", "-p", "35", "--stdout",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # espeak-ng no instalado (dev local sin el binario) → el front cae a "sin audio".
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tts no disponible") from None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(text.encode()), timeout=10)
    except TimeoutError:
        proc.kill()
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "tts timeout") from None
    if proc.returncode != 0 or not out:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "tts error")
    return Response(
        content=out,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400"},
    )
