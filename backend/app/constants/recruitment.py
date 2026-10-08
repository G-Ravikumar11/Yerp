"""The fixed lists, limits and statuses for recruitment."""



# How far ahead of an interview the nudge goes out.
INTERVIEW_REMINDER_HOURS = 24

# A requisition is the role being hired for. Application forms hang off it, so
# one job can have several intake forms (careers page, referral, agency) while
# reporting still rolls up to a single opening.
REQUISITION_STATUSES = ("draft", "open", "on_hold", "closed", "filled")
WORK_MODES = ("onsite", "hybrid", "remote")

INTERVIEW_MODES = ("video", "phone", "onsite")
INTERVIEW_STATUSES = ("scheduled", "completed", "cancelled", "no_show")
INTERVIEW_OUTCOMES = ("", "pass", "fail", "hold")

OFFER_STATUSES = ("draft", "sent", "accepted", "declined", "withdrawn")

MAX_DOCUMENTS_PER_APPLICATION = 6
