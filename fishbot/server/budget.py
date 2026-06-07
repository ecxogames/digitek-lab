BASE_PAY_PER_TASK = 100.0
OVERALL_LEVEL_MULTIPLIER = 0.02
FISHERMAN_LEVEL_MULTIPLIER = 0.05
TASKS_PER_MINUTE = 4.0


def work_time_seconds(settings):
    if not settings.get("timer"):
        return 60
    duration = int(settings.get("timerDuration", 60) or 60)
    unit = settings.get("timerUnit", "minutes")
    if unit == "hours":
        return duration * 3600
    if unit == "seconds":
        return duration
    return duration * 60


def calculate_work_income(overall_level, fisherman_level, excellent_employee, mood_percent, settings):
    work_time = work_time_seconds(settings)
    total_tasks = TASKS_PER_MINUTE * (work_time / 60.0)
    fail_chance = float(settings.get("failingMultiplier", 0) or 0)
    success_rate = (100.0 - fail_chance) / 100.0
    overall_level = _scale_new_job_level(overall_level)
    fisherman_level = _scale_new_job_level(fisherman_level)
    level_multiplier = 1.0 + (overall_level * OVERALL_LEVEL_MULTIPLIER) + (fisherman_level * FISHERMAN_LEVEL_MULTIPLIER)
    base_pay = BASE_PAY_PER_TASK * level_multiplier * mood_percent
    successful_tasks = total_tasks * success_rate
    income_without_pass = base_pay * successful_tasks
    employee_multiplier = 1.5 if excellent_employee else 1.0
    estimated_income = income_without_pass * employee_multiplier
    losses = (total_tasks - successful_tasks) * base_pay * employee_multiplier
    return [estimated_income, estimated_income - income_without_pass, losses]


def _scale_new_job_level(level):
    try:
        level = float(level or 1)
    except Exception:
        level = 1.0
    level = max(1.0, min(10.0, level))
    return level * 5.0


def format_money(amount):
    return "${:,.2f}".format(float(amount or 0))


def shorten_money(amount):
    amount = float(amount or 0)
    if amount >= 1_000_000:
        return "${:.1f}M".format(amount / 1_000_000)
    if amount >= 1_000:
        return "${:.1f}k".format(amount / 1_000)
    return format_money(amount)
