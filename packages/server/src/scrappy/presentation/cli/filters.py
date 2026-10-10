"""``--where "ram_gb>=16"``: the parser lives in the application layer (strategies share it)."""

from scrappy.application.filter_syntax import parse_where, parse_wheres

__all__ = ["parse_where", "parse_wheres"]
