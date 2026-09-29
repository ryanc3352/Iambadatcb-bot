"""Helpers shared by the routes_*.py files."""
from flask import request


def json_body():
    """Return the request's JSON object, or {} if there is none."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
