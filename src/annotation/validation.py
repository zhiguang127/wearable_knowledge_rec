"""Offline validation of the JSON Schema subset used by frozen audit schemas."""
import math
import re


def validate(value, schema, path="$"):
    errors = []
    if "anyOf" in schema:
        return [] if any(not validate(value, s, path) for s in schema["anyOf"]) else [path + ": anyOf mismatch"]
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list),
              "string": isinstance(value, str), "boolean": isinstance(value, bool), "null": value is None,
              "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
              "integer": isinstance(value, int) and not isinstance(value, bool)}
    if types and not any(checks.get(t, False) for t in types):
        return [path + ": type mismatch"]
    if "enum" in schema and not any(type(value) == type(v) and value == v for v in schema["enum"]):
        errors.append(path + ": enum mismatch")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [path + ": missing " + k for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            errors += [path + ": unexpected " + k for k in value if k not in properties]
        for k, v in value.items():
            if k in properties:
                errors += validate(v, properties[k], path + "." + k)
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], path + "[" + str(i) + "]")
    if isinstance(value, str) and "pattern" in schema and re.search(schema["pattern"], value) is None:
        errors.append(path + ": pattern mismatch")
    return errors
