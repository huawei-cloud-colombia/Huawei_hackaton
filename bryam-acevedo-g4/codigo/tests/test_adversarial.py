"""Bono D: suite de pruebas adversariales — patrones de ataque reales."""
from datetime import datetime, timezone

from app.engine import RiskEngine
from tests.helpers import make_txn
from tests.test_phase1 import no_flake_config


def test_card_testing_microtransaction_burst_is_declined():
    """6 microtransacciones en 7s (patrón clásico de card testing) -> la 6ª debe ser DECLINE."""
    engine = RiskEngine(no_flake_config())
    card = "card_microtest"
    amounts = [5000, 7000, 6000, 15000, 9000, 8000]
    result = None
    for i, amount in enumerate(amounts):
        result = engine.evaluate(
            make_txn(id=f"txn_{i}", card_id=card, amount=amount, country="CO", ip_country="CO")
        )
    assert result["decision"] == "DECLINE"
    assert any(r["rule"] == "velocity_limit_exceeded" for r in result["reasons"])


def test_ip_spoofing_between_consecutive_transactions_is_still_caught():
    """El atacante rota el país de la IP en cada transacción para evadir un filtro
    estático 'de una sola vez'; cada transacción individual debe seguir disparando
    country_mismatch (no hay forma de acumular exención cambiando IP)."""
    engine = RiskEngine(no_flake_config())
    card = "card_spoofer"
    spoofed_countries = ["RU", "NG", "VN"]
    for i, ip_country in enumerate(spoofed_countries):
        result = engine.evaluate(
            make_txn(id=f"txn_{i}", card_id=card, country="CO", ip_country=ip_country)
        )
        rules = {r["rule"] for r in result["reasons"]}
        assert "country_mismatch" in rules


def test_device_recycled_across_multiple_cards_is_flagged():
    """Un dispositivo 'reciclado' prueba 4 tarjetas distintas en 30s -> device_card_hopping."""
    engine = RiskEngine(no_flake_config())
    device = "dev_recycled"
    result = None
    for i in range(4):
        result = engine.evaluate(
            make_txn(id=f"txn_{i}", card_id=f"card_{i}", device_id=device, country="CO", ip_country="CO")
        )
    rules = {r["rule"] for r in result["reasons"]}
    assert "device_card_hopping" in rules
    assert result["decision"] == "DECLINE"


def test_blocked_card_cannot_slip_through_with_small_amount():
    """Tras el bloqueo, ni siquiera una microtransacción 'inocente' debe pasar."""
    engine = RiskEngine(no_flake_config())
    card = "card_after_block"
    for i in range(6):
        engine.evaluate(make_txn(id=f"txn_{i}", card_id=card, amount=5000, country="CO", ip_country="CO"))

    sneaky = engine.evaluate(
        make_txn(
            id="txn_sneaky",
            card_id=card,
            amount=1,
            country="CO",
            ip_country="CO",
            timestamp=datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc),
        )
    )
    assert sneaky["decision"] == "DECLINE"
    assert any(r["rule"] == "card_temporarily_blocked" for r in sneaky["reasons"])
