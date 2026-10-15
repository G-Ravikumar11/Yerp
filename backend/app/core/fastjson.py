"""A big answer, sent without FastAPI's value-by-value conversion.

Returning a dict from a route makes FastAPI walk every value of it (jsonable_encoder) before it is written as JSON.
For a screen of a hundred thousand values - a BOQ of four thousand lines - that walk alone was over a second of
the server's time, with the database answering in fifteen milliseconds. The answers built here are already plain
dicts, lists, strings and numbers, so they are written straight out by Python's own encoder; anything unusual
(a date, a Decimal) still goes through FastAPI's converter, so nothing breaks - it is only not slower.
"""
import json

from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response


def fast_json(payload, status_code=200):
    body = json.dumps(payload, default=jsonable_encoder, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return Response(content=body, status_code=status_code, media_type="application/json")
