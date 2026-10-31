"""The fixed lists, limits and statuses for projects."""



# JOBS
#
# A contracting business earns per job, not per month. Everything priced,
# bought or worked can point at one, and the costing rollup is the answer to
# the only question that decides whether to take the next job like it.
JOB_STATUSES = ("quoting", "won", "in_progress", "on_hold", "complete", "cancelled")
# The one status that means the work is done and the retention should be
# coming back. Named rather than spelled out at each use, because guessing
# at "completed" instead of "complete" silently reports nothing.
JOB_FINISHED = "complete"
assert JOB_FINISHED in JOB_STATUSES
# Once a job is in one of these it is history: it stays in reports but is kept
# out of the pickers, so nobody bills a site that finished last spring.
JOB_CLOSED_STATUSES = ("complete", "cancelled")

# THE SITE DIARY
#
# The daily record a site actually keeps. On a civil contract it is the
# document that settles a delay claim two years later, and it is also the
# only place the labour that went into the work is written down - so it is
# what turns "the job cost this much in material" into a real cost.
WEATHER = ("Clear", "Cloudy", "Rain", "Heavy rain")

# THE HINDRANCE REGISTER
#
# What held the work up, whose risk it was and what it cost in days: the record an extension of time is claimed from.
HINDRANCE_CAUSES = ("Rain / weather", "Drawings or details awaited", "Client decision awaited", "Site or front not handed over",
                    "Payment held up", "Material shortage", "Labour shortage", "Plant breakdown", "Utility shifting",
                    "Change in scope", "Statutory approval", "Other")
HINDRANCE_PARTIES = ("Client", "Contractor", "Subcontractor", "Neither (force majeure)")
HINDRANCE_STATUSES = ("Open", "Notified", "Agreed", "Rejected", "Closed")

# Why an activity is late against its baseline, when the hindrance register does not already say. An activity that slips has to
# carry one or the other, so every day of delay is accounted for when the extension of time is argued.
DELAY_REASONS = ("Predecessor finished late", "Drawings or details late", "Client decision late", "Front not available",
                 "Weather", "Material late", "Labour short", "Plant breakdown", "Quantity increased", "Rework",
                 "Productivity lower than planned", "Other")

DRAWING_DISCIPLINES = ("Architectural", "Structural", "Civil", "Electrical", "Plumbing", "Mechanical",
                       "STP / process", "Landscape", "Other")
