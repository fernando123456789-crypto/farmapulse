"""Validación de entradas."""

import re
from typing import Tuple


# Configuración de política de contraseñas
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
PASSWORD_REQUIRE_UPPERCASE = True
PASSWORD_REQUIRE_LOWERCASE = True
PASSWORD_REQUIRE_NUMBERS = True
PASSWORD_REQUIRE_SPECIAL = True

# Caracteres especiales permitidos
SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?"


def validar_contrasena(password: str) -> Tuple[bool, str]:
    """
    Valida una contraseña según la política de seguridad de FarmaPulse.
    
    Requisitos:
    - Mínimo 12 caracteres
    - Máximo 128 caracteres
    - Al menos una mayúscula
    - Al menos una minúscula
    - Al menos un número
    - Al menos un carácter especial
    
    Args:
        password: Contraseña a validar (sin procesar)
    
    Returns:
        Tuple[bool, str]: (es_válida, mensaje_error_o_exito)
        
    Ejemplos:
        >>> validar_contrasena("abc123")
        (False, "La contraseña debe tener al menos 12 caracteres")
        
        >>> validar_contrasena("Abc123!@#def")
        (True, "OK")
    """
    
    # Verificar que sea una cadena
    if not isinstance(password, str):
        return False, "La contraseña debe ser texto"
    
    # Verificar longitud mínima
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, f"La contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres"
    
    # Verificar longitud máxima (prevenir DoS)
    if len(password) > PASSWORD_MAX_LENGTH:
        return False, f"La contraseña no puede exceder {PASSWORD_MAX_LENGTH} caracteres"
    
    # Verificar mayúsculas
    if PASSWORD_REQUIRE_UPPERCASE and not re.search(r"[A-Z]", password):
        return False, "La contraseña debe contener al menos una mayúscula (A-Z)"
    
    # Verificar minúsculas
    if PASSWORD_REQUIRE_LOWERCASE and not re.search(r"[a-z]", password):
        return False, "La contraseña debe contener al menos una minúscula (a-z)"
    
    # Verificar números
    if PASSWORD_REQUIRE_NUMBERS and not re.search(r"[0-9]", password):
        return False, "La contraseña debe contener al menos un número (0-9)"
    
    # Verificar caracteres especiales
    if PASSWORD_REQUIRE_SPECIAL:
        if not re.search(rf"[{re.escape(SPECIAL_CHARS)}]", password):
            return False, f"La contraseña debe contener al menos un carácter especial: {SPECIAL_CHARS}"
    
    # Verificar que no contenga espacios en blanco
    if " " in password or "\t" in password or "\n" in password:
        return False, "La contraseña no puede contener espacios en blanco"
    
    # Todos los requisitos cumplidos
    return True, "OK"


def enmascarar_error_auth(error_original: str, tipo_error: str = "login") -> str:
    """
    Enmascara errores de autenticación de Supabase para evitar enumeración
    de usuarios y exposición de información sensible.
    
    Args:
        error_original: Mensaje de error original de Supabase
        tipo_error: "login", "signup", u otro
    
    Returns:
        str: Mensaje de error genérico seguro para mostrar al usuario
    """
    
    if not error_original:
        return "Error de autenticación"
    
    error_lower = error_original.lower()
    
    # Mapear errores comunes a mensajes genéricos
    errores_sensibles = {
        "user already registered": "Credenciales inválidas",
        "user_already_exists": "Credenciales inválidas",
        "invalid login credentials": "Credenciales inválidas",
        "invalid password": "Credenciales inválidas",
        "invalid email": "Credenciales inválidas",
        "user not found": "Credenciales inválidas",
        "email not confirmed": "Por favor, confirma tu correo electrónico",
        "email_not_confirmed": "Por favor, confirma tu correo electrónico",
        "weak password": "La contraseña no cumple con los requisitos de seguridad",
        "password too weak": "La contraseña no cumple con los requisitos de seguridad",
        "otp expired": "El código ha expirado. Solicita uno nuevo.",
        "invalid otp": "Código inválido o expirado",
        "too many requests": "Demasiados intentos. Intenta más tarde.",
        "rate limit": "Demasiados intentos. Intenta más tarde.",
    }
    
    # Buscar coincidencias
    for patron, mensaje_generico in errores_sensibles.items():
        if patron in error_lower:
            return mensaje_generico
    
    # Error desconocido - devolver mensaje genérico
    return "Ocurrió un error. Intenta más tarde o contacta al soporte."


def validar_email(email: str) -> Tuple[bool, str]:
    """
    Valida formato básico de email.
    
    Args:
        email: Email a validar
    
    Returns:
        Tuple[bool, str]: (es_válido, mensaje)
    """
    
    if not email:
        return False, "El correo electrónico es requerido"
    
    email = email.strip().lower()
    
    # Validación básica (RFC 5322 simplificada)
    patron_email = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    
    if not re.match(patron_email, email):
        return False, "Formato de correo electrónico inválido"
    
    if len(email) > 254:  # Límite RFC 5321
        return False, "El correo electrónico es demasiado largo"
    
    return True, "OK"


def sanitizar_termino_busqueda(termino: str, max_chars: int = 100) -> Tuple[bool, str, str]:
    """
    Sanitiza y valida un término de búsqueda para prevenir inyecciones
    y ataques de DoS.
    
    Args:
        termino: Término a validar
        max_chars: Máximo de caracteres permitidos
    
    Returns:
        Tuple[bool, str, str]: (es_válido, mensaje, termino_limpio)
    """
    
    if not termino:
        return False, "El término de búsqueda es requerido", ""
    
    termino = termino.strip()
    
    if len(termino) > max_chars:
        return False, f"Término muy largo (máximo {max_chars} caracteres)", ""
    
    if len(termino) < 2:
        return False, "El término debe tener al menos 2 caracteres", ""
    
    # Caracteres permitidos: letras, números, espacios, y algunos caracteres comunes
    # Incluye acentos comunes en español
    patron = r"^[a-zA-Z0-9\s\-áéíóúñÁÉÍÓÚÑ.,';/()]+$"
    
    if not re.match(patron, termino):
        return False, "El término contiene caracteres no permitidos", ""
    
    # Evitar múltiples espacios seguidos
    termino = re.sub(r"\s+", " ", termino)
    
    return True, "OK", termino


class SeguridadConfiguracion:
    """
    Clase de configuración centralizada para políticas de seguridad.
    Facilita ajustes rápidos sin modificar múltiples archivos.
    """
    
    # Contraseñas
    PASSWORD_MIN_LENGTH = PASSWORD_MIN_LENGTH
    PASSWORD_MAX_LENGTH = PASSWORD_MAX_LENGTH
    PASSWORD_REQUIRE_UPPERCASE = PASSWORD_REQUIRE_UPPERCASE
    PASSWORD_REQUIRE_LOWERCASE = PASSWORD_REQUIRE_LOWERCASE
    PASSWORD_REQUIRE_NUMBERS = PASSWORD_REQUIRE_NUMBERS
    PASSWORD_REQUIRE_SPECIAL = PASSWORD_REQUIRE_SPECIAL
    
    # Rate limiting (en segundos)
    AUTH_RATE_LIMIT_LOGIN = "5 per minute"      # 5 intentos por minuto
    AUTH_RATE_LIMIT_SIGNUP = "3 per minute"     # 3 registros por minuto
    AUTH_RATE_LIMIT_GENERAL = "50 per hour"     # Límite general
    
    # Sesión
    SESSION_TIMEOUT_MINUTES = 60      # Inactividad (opcional con JWT de Supabase)
    SESSION_ABSOLUTE_TIMEOUT_DAYS = 30  # Expiración máxima
    
    # Búsqueda
    BUSQUEDA_MAX_CHARS = 100
    BUSQUEDA_TIMEOUT_SEGUNDOS = 30
    
    # Email
    EMAIL_MAX_LENGTH = 254
    
    # Intentos fallidos
    MAX_LOGIN_ATTEMPTS = 5           # Máximo de intentos antes de bloquear
    LOGIN_LOCKOUT_MINUTES = 15       # Tiempo de bloqueo
    
    @classmethod
    def get_config_dict(cls):
        """Retorna la configuración como diccionario."""
        return {
            k: v for k, v in vars(cls).items() 
            if not k.startswith("_") and not callable(v)
        }


# Para testing
if __name__ == "__main__":
    print("=== PRUEBAS DE VALIDACIÓN ===\n")
    
    # Pruebas de contraseña
    test_passwords = [
        ("abc123", "Muy corta y sin caracteres especiales"),
        ("Abc123!@#", "Menos de 12 caracteres"),
        ("Abc123!@#def", "✓ Válida"),
        ("abc123!@#def", "Sin mayúscula"),
        ("ABC123!@#DEF", "Sin minúscula"),
        ("Abcdefg!@#def", "Sin número"),
        ("Abc123def", "Sin carácter especial"),
    ]
    
    for pwd, descripcion in test_passwords:
        es_valida, msg = validar_contrasena(pwd)
        estado = "✓" if es_valida else "✗"
        print(f"{estado} {descripcion}")
        print(f"  Contraseña: {pwd}")
        print(f"  Resultado: {msg}\n")
    
    # Pruebas de email
    print("\n=== PRUEBAS DE EMAIL ===\n")
    test_emails = [
        ("usuario@example.com", "✓ Válido"),
        ("usuario", "Sin @"),
        ("usuario@", "Sin dominio"),
        ("usuario@dominio", "Sin TLD"),
        ("usuario@dominio.com", "✓ Válido"),
    ]
    
    for email, descripcion in test_emails:
        es_valido, msg = validar_email(email)
        print(f"{descripcion}: {email} - {msg}\n")
    
    # Pruebas de término de búsqueda
    print("\n=== PRUEBAS DE BÚSQUEDA ===\n")
    test_terminos = [
        ("ibuprofeno", "✓ Válido"),
        ("i", "Muy corto"),
        ("<script>alert('xss')</script>", "Inyección XSS"),
        ("paracetamol 500mg", "✓ Válido con espacios"),
        ("a" * 150, "Demasiado largo"),
    ]
    
    for termino, descripcion in test_terminos:
        es_valido, msg, limpio = sanitizar_termino_busqueda(termino)
        print(f"{descripcion}")
        print(f"  Original: {termino[:50]}...")
        print(f"  Válido: {es_valido} - {msg}\n")
