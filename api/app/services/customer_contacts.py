import phonenumbers
from app.services.tenant_security import Registration


def normalize_phone(value: str | None, *, required: bool = False) -> str | None:
    if not value or not value.strip():
        if required:
            raise ValueError("Customer phone number is required")
        return None
    try:
        number = phonenumbers.parse(value.strip(), "IN")
    except phonenumbers.NumberParseException as error:
        raise ValueError("Enter a valid phone number; include the country code outside India") from error
    if not phonenumbers.is_valid_number(number):
        raise ValueError("Enter a valid phone number; include the country code outside India")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    if len(value.strip()) > 254:
        raise ValueError("Enter a valid email address")
    return Registration.clean_email(value)
