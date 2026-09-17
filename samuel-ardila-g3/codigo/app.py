from flask import Flask, jsonify, request, render_template
from concurrent.futures import ThreadPoolExecutor, as_completed
import config
import db
from services import seat_service, hold_service, audit_service
from services import queue_service, idempotency_service
from services import payment_service, recurrence_service

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/seats")
def api_seats():
    section = request.args.get("section")
    seats = seat_service.get_seats(section)
    return jsonify({"seats": seats, "count": len(seats)})


@app.route("/api/holds", methods=["POST"])
def api_create_hold():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    event_id = body.get("event_id", config.EVENT_ID)
    seat_ids = body.get("seat_ids")
    idem_key = request.headers.get("Idempotency-Key")

    idem_payload = {"user_id": user_id, "event_id": event_id, "seat_ids": seat_ids}
    action, cached = idempotency_service.resolve(idem_key, idem_payload)
    if action == "replay":
        return jsonify(cached), 200
    if action == "conflict":
        return jsonify({"error": "IDEMPOTENCY_CONFLICT", "key": idem_key}), 409

    try:
        with queue_service.session_queue.session(timeout=config.QUEUE_TIMEOUT_SECONDS):
            result = hold_service.create_hold(user_id, event_id, seat_ids)
    except queue_service.QueueFullError:
        return jsonify({"error": "service_busy", "message": "queue_full"}), 503

    if "error" not in result and idem_key:
        idempotency_service.store(idem_key, idem_payload, result.get("hold_id"), result)

    if "error" in result:
        return jsonify(result), result.pop("status", 500)
    return jsonify(result), 201


@app.route("/api/holds/<hold_id>")
def api_get_hold(hold_id):
    hold = hold_service.get_hold(hold_id)
    if not hold:
        return jsonify({"error": "hold_not_found"}), 404
    return jsonify(hold)


@app.route("/api/holds/<hold_id>", methods=["DELETE"])
def api_release_hold(hold_id):
    result = hold_service.release_hold(hold_id)
    if "error" in result:
        return jsonify(result), result.pop("status", 500)
    return jsonify(result)


@app.route("/api/holds/expire", methods=["POST"])
def api_expire_holds():
    count = hold_service.expire_holds()
    return jsonify({"expired": count})


@app.route("/api/holds/<hold_id>/confirm", methods=["POST"])
def api_confirm_hold(hold_id):
    body = request.get_json(silent=True) or {}
    payment_token = body.get("payment_token")
    scenario = body.get("scenario", "AUTO")
    result = payment_service.confirm_hold(hold_id, payment_token, scenario)
    if "error" in result:
        return jsonify(result), result.pop("status", 500)
    return jsonify(result)


@app.route("/api/circuit-breaker")
def api_circuit_breaker():
    return jsonify(payment_service.get_circuit_breaker_state())


@app.route("/api/circuit-breaker/reset", methods=["POST"])
def api_reset_circuit_breaker():
    return jsonify(payment_service.reset_circuit_breaker())


@app.route("/api/recurrences/<hold_id>")
def api_get_recurrence(hold_id):
    rec = recurrence_service.get_recurrence(hold_id)
    if not rec:
        return jsonify({"error": "no_recurrence"}), 404
    return jsonify(rec)


@app.route("/api/recurrences/<hold_id>/charge", methods=["POST"])
def api_charge_recurrence(hold_id):
    body = request.get_json(silent=True) or {}
    scenario = body.get("scenario", "AUTO")
    result = recurrence_service.charge_next(hold_id, scenario)
    if "error" in result:
        return jsonify(result), result.pop("status", 500)
    return jsonify(result)


@app.route("/api/audit/<hold_id>")
def api_audit(hold_id):
    return jsonify({"hold_id": hold_id, "history": audit_service.get_audit(hold_id)})


@app.route("/api/audit")
def api_audit_all():
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    return jsonify({"history": audit_service.get_audit_all(limit, offset)})


@app.route("/api/queue/stats")
def api_queue_stats():
    return jsonify(queue_service.session_queue.stats())


@app.route("/api/simulate/race", methods=["POST"])
def api_simulate_race():
    body = request.get_json(silent=True) or {}
    seat_id = body.get("seat_id")
    n = body.get("n", 20)
    if not seat_id:
        return jsonify({"error": "seat_id_required"}), 400

    def attempt(i):
        return hold_service.create_hold(f"usr_race_{i}", config.EVENT_ID, [seat_id])

    results = []
    with ThreadPoolExecutor(max_workers=min(n, 100)) as pool:
        futures = [pool.submit(attempt, i) for i in range(n)]
        for f in as_completed(futures):
            results.append(f.result())

    winners = [r for r in results if "hold_id" in r and "error" not in r]
    rejected = [r for r in results if "error" in r]
    return jsonify({
        "seat_id": seat_id,
        "total_requests": n,
        "winners": len(winners),
        "rejected": len(rejected),
        "overselling": max(0, len(winners) - 1),
        "winner_hold": winners[0]["hold_id"] if winners else None,
    })


@app.route("/api/config")
def api_config():
    return jsonify({
        "HOLD_TTL_SECONDS": config.HOLD_TTL_SECONDS,
        "MAX_SEATS_PER_USER": config.MAX_SEATS_PER_USER,
        "QUEUE_MAX_CONCURRENT": config.QUEUE_MAX_CONCURRENT,
        "EVENT_ID": config.EVENT_ID,
        "CURRENCY": config.CURRENCY,
    })


@app.route("/api/config", methods=["POST"])
def api_update_config():
    body = request.get_json(silent=True) or {}
    if "HOLD_TTL_SECONDS" in body:
        config.HOLD_TTL_SECONDS = int(body["HOLD_TTL_SECONDS"])
    if "MAX_SEATS_PER_USER" in body:
        config.MAX_SEATS_PER_USER = int(body["MAX_SEATS_PER_USER"])
    return jsonify({
        "HOLD_TTL_SECONDS": config.HOLD_TTL_SECONDS,
        "MAX_SEATS_PER_USER": config.MAX_SEATS_PER_USER,
    })


def bootstrap():
    db.init_schema()
    db.seed_seats()
    hold_service.start_expiry_worker()
    recurrence_service.start_recurrence_worker()


bootstrap()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
