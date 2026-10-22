
"""Calculate public transit fares and manage transit cards."""

import hashlib
from pathlib import Path

import paramiko
from defusedxml import ElementTree


# Fictional city fare rules.
DISTANCE_SLABS = [(2, 10), (5, 20), (12, 30), (21, 40), (32, 50)]
MAX_FARE = 60
DAILY_CAP = 150
OFF_PEAK_DISCOUNT = 0.10
CONCESSIONS = {"student": 0.25, "senior": 0.50}

cards = {}


def base_of(km):
    """Return the base fare for a journey distance."""
    return fare_for_distance(km)


def fare_for_distance(km):
    """Return the fare for the given distance in kilometres."""
    if km < 0:
        raise ValueError("Distance cannot be negative.")

    for limit, fare in DISTANCE_SLABS:
        if km < limit:
            return fare

    return MAX_FARE


def is_peak(time_hhmm):
    """Return whether the journey occurs during peak hours."""
    try:
        hour_text, minute_text = time_hhmm.split(":")
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Time must use HH:MM format.") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be a valid 24-hour time.")

    return (8 <= hour <= 10) or (17 <= hour <= 20)


def journey_fare(km, time_hhmm, categories):
    """Calculate a journey fare after applicable discounts."""
    fare = base_of(km)

    if not is_peak(time_hhmm):
        fare *= 1 - OFF_PEAK_DISCOUNT

    for category in categories:
        if category not in CONCESSIONS:
            raise ValueError(f"Unknown concession category: {category}")
        fare *= 1 - CONCESSIONS[category]

    return round(fare, 2)


def daily_total(journeys):
    """Return the daily journey fare total, limited by the daily cap."""
    fares = (
        journey_fare(km, time, categories)
        for km, time, categories in journeys
    )
    return round(min(sum(fares), DAILY_CAP), 2)


def issue_card(card_id, balance=0):
    """Create a transit card with an initial balance."""
    if balance < 0:
        raise ValueError("Initial balance cannot be negative.")

    cards[card_id] = {"balance": balance, "trips": []}


def tap_out(card_id, km, time_hhmm, categories=None):
    """Deduct the journey fare and record a completed trip."""
    if card_id not in cards:
        raise KeyError(f"Unknown card: {card_id}")

    if categories is None:
        categories = []

    fare = journey_fare(km, time_hhmm, categories)
    cards[card_id]["balance"] = round(
        cards[card_id]["balance"] - fare, 2
    )
    cards[card_id]["trips"].append((km, time_hhmm, fare))

    return cards[card_id]["balance"]


def top_up(card_id, amount):
    """Add money to a transit card and return its new balance."""
    if card_id not in cards:
        raise KeyError(f"Unknown card: {card_id}")

    if amount <= 0:
        raise ValueError("Top-up amount must be positive.")

    cards[card_id]["balance"] = round(
        cards[card_id]["balance"] + amount, 2
    )
    return cards[card_id]["balance"]


def cheapest_route(routes):
    """Return the route with the lowest base fare."""
    if not routes:
        raise ValueError("At least one route is required.")

    return min(routes, key=base_of)


def ticket_checksum(ticket_text):
    """Return a SHA-256 checksum of the ticket text."""
    return hashlib.sha256(ticket_text.encode("utf-8")).hexdigest()


def load_stops(xml_text):
    """Safely parse XML and return the names of transit stops."""
    root = ElementTree.fromstring(xml_text)

    return [
        stop.attrib["name"]
        for stop in root.iter("stop")
        if "name" in stop.attrib
    ]


def push_fares_to_gate(gate_host, fare_file):
    """Upload a fare file over SSH after verifying the host key."""
    file_path = Path(fare_file)

    if not file_path.is_file():
        raise FileNotFoundError(f"Fare file not found: {fare_file}")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
        client.connect(
            gate_host,
            username="depot",
            timeout=10,
        )

        remote_path = file_path.name

        with client.open_sftp() as sftp:
            sftp.put(str(file_path), remote_path)
    finally:
        client.close()


def main():
    """Demonstrate the transit fare calculator features."""
    print("Fare for exactly 2 km:", fare_for_distance(2))
    print("Fare for exactly 32 km:", fare_for_distance(32))
    print("Is 20:45 peak?", is_peak("20:45"))

    print(
        "Student + senior card, 10 km off-peak:",
        journey_fare(10, "14:00", ["student", "senior"]),
    )

    day = [
        (30, "08:15", []),
        (30, "18:30", []),
        (40, "21:00", []),
        (35, "22:30", []),
    ]
    print("Daily total (cap 150):", daily_total(day))

    issue_card("C1", 25)
    print(
        "Balance after a 30 km trip with Rs.25:",
        tap_out("C1", 30, "09:00"),
    )

    issue_card("C2", 0)
    print(
        "Top up 0.1 then 0.2:",
        top_up("C2", 0.1),
        top_up("C2", 0.2),
    )

    print(
        "Cheapest of routes 12 km / 5 km / 21 km:",
        cheapest_route([12, 5, 21]),
    )
    print("Ticket checksum:", ticket_checksum("C1|30km|09:00"))

    sample_xml = (
        "<line><stop name='Central'/>"
        "<stop name='Market'/></line>"
    )
    print("Stops:", load_stops(sample_xml))


if __name__ == "__main__":
    main()
