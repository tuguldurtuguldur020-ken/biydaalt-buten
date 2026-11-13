"""Evaluate a user-configured schedule, without claiming an official offence."""
from dataclasses import asdict, dataclass
from datetime import datetime
from .plates import normalize_plate
import re
from .settings import UB_TIME, now_ub

DAY_NAMES = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]


def rule_plate(text):
    """Manual schedule checks accept four digits; OCR still requires a full plate."""
    value = str(text).strip()
    digits = re.sub(r"[\s-]", "", value)
    return digits if re.fullmatch(r"[0-9]{4}", digits) else normalize_plate(value)


def restriction_days(plate, rules):
    value = rule_plate(plate)
    if not value or rules.get("mode", "weekly") != "weekly":
        return []
    digit = int(value[3])
    return [day for day in range(7) if digit in rules.get("weekdays", {}).get(str(day), [])]


@dataclass
class RuleResult:
    code: str
    label: str
    restricted_today: bool = False
    restricted_now: bool = False
    detail: str = ""

    def as_dict(self):
        return asdict(self)


def evaluate(plate, rules, at=None):
    at = at or now_ub()
    at = at.replace(tzinfo=UB_TIME) if at.tzinfo is None else at.astimezone(UB_TIME)
    plate = rule_plate(plate)
    if not plate:
        return RuleResult("unknown", "Дугаар тодорхойгүй")
    if rules.get("mode") == "off":
        return RuleResult("off", "Шалгалт унтраалттай")
    if not rules.get("in_zone", True):
        return RuleResult("out_of_zone", "Бүсийн гадна", detail="Хязгаарлалтын бүсийн гадна гэж тохируулсан.")
    exempt = {normalize_plate(p) for p in rules.get("exempt_plates", [])}
    if plate in exempt:
        return RuleResult("exempt", "Чөлөөлсөн дугаар")
    if at.date().isoformat() in rules.get("holidays", []):
        return RuleResult("holiday", "Чөлөөлсөн өдөр")
    last_digit = int(plate[3])
    mode = rules.get("mode", "weekly")
    if mode == "weekly":
        restricted = last_digit in rules.get("weekdays", {}).get(str(at.weekday()), [])
    elif mode == "odd_even":
        same_parity = last_digit % 2 == at.day % 2
        allowed = same_parity if rules.get("even_on_even_date", True) else not same_parity
        restricted = not allowed
    else:
        return RuleResult("unknown", "Хуваарь тодорхойгүй")
    start = datetime.strptime(rules.get("start", "08:00"), "%H:%M").time()
    end = datetime.strptime(rules.get("end", "20:00"), "%H:%M").time()
    current = at.time().replace(tzinfo=None)
    in_hours = start <= current < end if start < end else current >= start or current < end
    detail = f"{DAY_NAMES[at.weekday()]} · сүүлийн цифр {last_digit} · {start:%H:%M}–{end:%H:%M} · тохируулсан хуваарь"
    if restricted and in_hours:
        return RuleResult("restricted", "Одоо хязгаарлалттай", True, True, detail)
    if restricted:
        return RuleResult("outside_hours", "Өнөөдөр хязгаарлах өдөр • цагаас гадна", True, False, detail)
    return RuleResult("allowed", "Хуваариар зорчих боломжтой", False, False, detail)
