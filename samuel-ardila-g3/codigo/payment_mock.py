import random
import time
import secrets

import config


def mock_payment_authorize(amount, currency, token, scenario="AUTO"):
    """
    Escenarios:
      APPROVED    -> pago aprobado
      DECLINED    -> pago rechazado
      ERROR       -> error del proveedor (500)
      TIMEOUT     -> latencia > 2s
      RECURRENCE  -> aprobado con flag recurring
      AUTO        -> 70% approved, 10% declined, 10% error, 10% timeout
    """
    if not token:
        return {"result": "ERROR", "reason": "empty_payment_token"}

    if scenario == "AUTO":
        r = random.random()
        if r < 0.70:
            scenario = "APPROVED"
        elif r < 0.80:
            scenario = "DECLINED"
        elif r < 0.90:
            scenario = "ERROR"
        else:
            scenario = "TIMEOUT"

    if scenario == "APPROVED":
        time.sleep(0.05)
        return {
            "result": "APPROVED",
            "auth_code": "auth_" + secrets.token_hex(6).upper(),
            "amount": amount,
            "currency": currency,
        }

    if scenario == "DECLINED":
        time.sleep(0.05)
        return {
            "result": "DECLINED",
            "reason": "insufficient_funds",
            "amount": amount,
            "currency": currency,
        }

    if scenario == "ERROR":
        time.sleep(0.05)
        return {
            "result": "ERROR",
            "reason": "provider_500",
            "amount": amount,
            "currency": currency,
        }

    if scenario == "TIMEOUT":
        time.sleep(config.PAYMENT_TIMEOUT_SECONDS + 0.5)
        return {
            "result": "TIMEOUT",
            "reason": "provider_unresponsive",
            "amount": amount,
            "currency": currency,
        }

    if scenario == "RECURRENCE":
        time.sleep(0.05)
        return {
            "result": "APPROVED",
            "auth_code": "auth_" + secrets.token_hex(6).upper(),
            "recurring": True,
            "amount": amount,
            "currency": currency,
        }

    return {"result": "ERROR", "reason": "unknown_scenario"}
