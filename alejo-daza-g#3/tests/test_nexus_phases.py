import subprocess
import sys


def _run(script: str, *args: str) -> None:
    proc = subprocess.run(
        [sys.executable, script, *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"


def test_fase2_last_seat_race():
    _run("stress_test_fase2.py", "30")


def test_fase3_payment_and_circuit_breaker():
    _run("stress_test_fase3.py")


def test_traceability_persistence():
    _run("trace_test.py")
