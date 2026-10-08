"""The Y ERP backend.

core/        what every part relies on: configuration, security, who is calling, money, files, the scheduler
schemas/     what each endpoint is sent
services/    the rules and workings behind the endpoints
routers/     the endpoints themselves
documents/   printed and Excel documents
validators/  checks on what people type
constants/   the fixed lists and limits each area works to

Importing any part of the package builds the whole application first, in the order bootstrap.py sets out, so a
script that imports one service gets the same, fully wired modules as the server does.
"""
from app import bootstrap  # noqa: F401
