#!/usr/bin/env python3
"""
Validates diagnosis JSON output against expected causes.
Strict validation: exact cause set match, valid schema, correct locations.
"""

import json
import os
import sys

try:
    import jsonschema
except ImportError:
    jsonschema = None


SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "schemas",
    "diagnosis.schema.json",
)


def validate_diagnosis(stdout_text, expected_causes):
    """
    Validate diagnosis JSON from tool stdout.

    Args:
        stdout_text: The raw stdout from the tool
        expected_causes: List of expected cause dicts with at minimum "type" field

    Returns:
        {"valid": bool, "error": str or None}
    """

    # Parse JSON from stdout
    diagnosis = _parse_diagnosis_json(stdout_text)
    if diagnosis is None:
        return {
            "valid": False,
            "error": f"Could not parse diagnosis JSON from stdout: {stdout_text[:200]}",
        }

    # Validate against schema
    schema_error = _validate_schema(diagnosis)
    if schema_error:
        return {"valid": False, "error": f"Schema validation failed: {schema_error}"}

    # Check status field
    if diagnosis.get("status") != "unreproducible":
        return {
            "valid": False,
            "error": f"Expected status 'unreproducible', got '{diagnosis.get('status')}'",
        }

    # Extract cause types from diagnosis
    actual_causes = diagnosis.get("causes", [])
    actual_types = sorted([c["type"] for c in actual_causes])
    expected_types = sorted([c["type"] for c in expected_causes])

    # Strict matching: exact cause set
    if actual_types != expected_types:
        missing = set(expected_types) - set(actual_types)
        extra = set(actual_types) - set(expected_types)
        parts = []
        if missing:
            parts.append(f"missing: {sorted(missing)}")
        if extra:
            parts.append(f"extra: {sorted(extra)}")
        return {
            "valid": False,
            "error": f"Cause set mismatch: {', '.join(parts)}",
        }

    # Validate location references
    for cause in actual_causes:
        location = cause.get("location", "")
        if not location or ":" not in location:
            return {
                "valid": False,
                "error": f"Invalid location format for {cause['type']}: '{location}'",
            }
        # Verify file:line format
        parts = location.rsplit(":", 1)
        if len(parts) != 2:
            return {
                "valid": False,
                "error": f"Location must be file:line format: '{location}'",
            }
        try:
            int(parts[1])
        except ValueError:
            return {
                "valid": False,
                "error": f"Location line must be integer: '{location}'",
            }

    # Validate expected locations if provided
    for expected_cause in expected_causes:
        if "location" in expected_cause:
            exp_type = expected_cause["type"]
            exp_loc = expected_cause["location"]

            matching = [c for c in actual_causes if c["type"] == exp_type]
            if matching:
                actual_loc = matching[0]["location"]
                # Allow partial match (file must match, line can differ slightly)
                exp_file = exp_loc.rsplit(":", 1)[0]
                actual_file = actual_loc.rsplit(":", 1)[0]
                if exp_file != actual_file:
                    return {
                        "valid": False,
                        "error": (
                            f"Location file mismatch for {exp_type}: "
                            f"expected '{exp_file}', got '{actual_file}'"
                        ),
                    }

    return {"valid": True, "error": None}


def _parse_diagnosis_json(text):
    """Try to parse diagnosis JSON from text, handling potential noise."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in output
    start = text.find("{")
    if start >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break

    return None


def _validate_schema(diagnosis):
    """Validate diagnosis against JSON schema. Returns error string or None."""
    if jsonschema is None:
        # Skip schema validation if jsonschema not available
        # Do basic structural checks instead
        if not isinstance(diagnosis, dict):
            return "diagnosis must be an object"
        if "status" not in diagnosis:
            return "missing 'status' field"
        if "causes" not in diagnosis:
            return "missing 'causes' field"
        if not isinstance(diagnosis["causes"], list):
            return "'causes' must be an array"
        if len(diagnosis["causes"]) == 0:
            return "'causes' must not be empty"
        for i, cause in enumerate(diagnosis["causes"]):
            if not isinstance(cause, dict):
                return f"causes[{i}] must be an object"
            if "type" not in cause:
                return f"causes[{i}] missing 'type'"
            if "location" not in cause:
                return f"causes[{i}] missing 'location'"
        return None

    try:
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema.validate(diagnosis, schema)
        return None
    except jsonschema.ValidationError as e:
        return str(e.message)
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <diagnosis.json> [expected_causes.json]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        stdout_text = f.read()

    expected = []
    if len(sys.argv) > 2:
        with open(sys.argv[2]) as f:
            expected = json.load(f)

    result = validate_diagnosis(stdout_text, expected)
    if result["valid"]:
        print("VALID")
        sys.exit(0)
    else:
        print(f"INVALID: {result['error']}")
        sys.exit(1)
