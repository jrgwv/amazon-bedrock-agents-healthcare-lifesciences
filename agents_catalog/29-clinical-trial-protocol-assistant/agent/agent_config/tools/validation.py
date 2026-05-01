"""
Input validation helpers for the Clinical Trial Protocol Assistant.

These are pure functions with no side effects — they validate and normalize
user-supplied inputs before they are passed to the ClinicalTrials.gov API.
"""

import re

# Canonical phase strings, in order.
_CANONICAL_PHASES = ["Phase 1", "Phase 2", "Phase 3", "Phase 4"]

# Pre-compiled pattern: matches "phase" (case-insensitive) followed by an
# optional separator (space, hyphen, or nothing) and then a single digit 1–4.
_PHASE_PATTERN = re.compile(r"^\s*phase\s*[-]?\s*([1-4])\s*$", re.IGNORECASE)


def validate_disease_area(s: str) -> str:
    """Validate and normalize a disease area string.

    Strips leading and trailing whitespace from *s*, then checks that the
    resulting string is between 2 and 500 characters (inclusive).

    Args:
        s: The raw disease area string supplied by the user.

    Returns:
        The stripped string when it passes validation.

    Raises:
        ValueError: If the stripped string is fewer than 2 characters, raises
            "Disease area must be at least 2 characters long."
            If the stripped string is greater than 500 characters, raises
            "Disease area must be 500 characters or fewer."

    Examples:
        >>> validate_disease_area("  type 2 diabetes  ")
        'type 2 diabetes'
        >>> validate_disease_area("x")
        Traceback (most recent call last):
            ...
        ValueError: Disease area must be at least 2 characters long.
    """
    stripped = s.strip()
    length = len(stripped)
    if length < 2:
        raise ValueError("Disease area must be at least 2 characters long.")
    if length > 500:
        raise ValueError("Disease area must be 500 characters or fewer.")
    return stripped


def normalize_trial_phase(s: str) -> str:
    """Normalize a trial phase string to its canonical form.

    Accepts any case/spacing variation of "Phase 1", "Phase 2", "Phase 3",
    or "Phase 4" — including forms such as "phase1", "PHASE 1", "Phase  1",
    "phase 1", "phase-1", and "Phase1" — and returns the canonical string
    (e.g., "Phase 1").

    The normalization process strips whitespace, lowercases the input, removes
    all internal spaces, and maps the result to a canonical form.

    Args:
        s: The raw trial phase string supplied by the user.

    Returns:
        One of "Phase 1", "Phase 2", "Phase 3", or "Phase 4".

    Raises:
        ValueError: If *s* cannot be normalized to one of the four accepted
            phases. Message: "Invalid trial phase. Accepted values: 'Phase 1',
            'Phase 2', 'Phase 3', 'Phase 4'."

    Examples:
        >>> normalize_trial_phase("phase1")
        'Phase 1'
        >>> normalize_trial_phase("PHASE 3")
        'Phase 3'
        >>> normalize_trial_phase("Phase  2")
        'Phase 2'
        >>> normalize_trial_phase("phase-4")
        'Phase 4'
        >>> normalize_trial_phase("Phase 5")
        Traceback (most recent call last):
            ...
        ValueError: Invalid trial phase. Accepted values: 'Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'.
    """
    match = _PHASE_PATTERN.match(s)
    if match:
        digit = match.group(1)
        return f"Phase {digit}"

    raise ValueError(
        "Invalid trial phase. Accepted values: 'Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'."
    )
