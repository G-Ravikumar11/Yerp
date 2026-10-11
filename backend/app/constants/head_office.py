"""The fixed lists and limits for head office."""

# How many rows each list on the HO portal carries. The full registers are a click away.
HO_LIST_LIMIT = 50

# Projects that do not need a BOQ opened: lost, finished or stopped.
HO_QUIET_JOB_STATUSES = ("complete", "cancelled")

# What waits on somebody but is not head office's to follow up - a person's leave is between them and HR.
HO_FOLLOW_UP_SKIPS = ("leave",)
