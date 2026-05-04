"""
Strands @tool functions and data models for the Clinical Trial Protocol Assistant.

This module contains:
  - Data model dataclasses (TrialRecord, EndpointPattern, CriteriaPattern,
    SampleSizeStats, AnalysisResult, ProtocolOutlineResult) used as structured
    return types throughout the agent's tool pipeline.
  - The three Strands @tool functions: search_clinical_trials, analyze_protocols,
    and generate_protocol_outline, which together implement the agent's core
    capability of searching ClinicalTrials.gov, analyzing retrieved protocols for
    common patterns, and generating a structured draft protocol outline with
    evidence-based, cited recommendations.

All tool functions are pure with respect to side effects beyond HTTP calls and
are independently testable.
"""

from dataclasses import dataclass, field
from typing import Optional, List
import statistics
import time
import requests
from strands import tool
from .validation import validate_disease_area, normalize_trial_phase

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TrialRecord:
    """A single clinical trial record retrieved from ClinicalTrials.gov.

    Attributes:
        nct_id: NCT identifier, e.g. "NCT01234567".
        title: Official trial title, or None if not available.
        primary_completion_date: ISO date string, e.g. "2022-03-15", or None.
        primary_endpoints: List of primary outcome measure descriptions.
        secondary_endpoints: List of secondary outcome measure descriptions.
        eligibility_criteria: Full eligibility text block, or None.
        enrollment: Planned enrollment count, or None if not available.
        url: ClinicalTrials.gov study URL, e.g.
            "https://clinicaltrials.gov/study/NCT01234567".
    """

    nct_id: str
    title: Optional[str]
    primary_completion_date: Optional[str]
    primary_endpoints: List[str]
    secondary_endpoints: List[str]
    eligibility_criteria: Optional[str]
    enrollment: Optional[int]
    url: str


@dataclass
class EndpointPattern:
    """A frequently occurring endpoint pattern identified across trials.

    Attributes:
        text: Endpoint description text.
        frequency: Number of trials containing this endpoint.
        nct_ids: NCT identifiers of the trials in which this endpoint appears.
    """

    text: str
    frequency: int
    nct_ids: List[str]


@dataclass
class CriteriaPattern:
    """A frequently occurring eligibility criteria pattern identified across trials.

    Attributes:
        pattern: Criteria pattern description.
        frequency: Number of trials containing this pattern.
        nct_ids: NCT identifiers of the trials in which this pattern appears.
    """

    pattern: str
    frequency: int
    nct_ids: List[str]


@dataclass
class SampleSizeStats:
    """Descriptive statistics for enrollment counts across analyzed trials.

    Attributes:
        median: Median enrollment count, or None if no enrollment data available.
        minimum: Minimum enrollment count, or None if no enrollment data available.
        maximum: Maximum enrollment count, or None if no enrollment data available.
        count: Number of trials with enrollment data (non-None enrollment values).
    """

    median: Optional[float]
    minimum: Optional[int]
    maximum: Optional[int]
    count: int


@dataclass
class AnalysisResult:
    """Structured output of the analyze_protocols tool.

    All frequency lists are sorted descending by frequency.

    Attributes:
        primary_endpoints: Frequently occurring primary endpoint patterns.
        secondary_endpoints: Frequently occurring secondary endpoint patterns.
        inclusion_criteria: Frequently occurring inclusion criteria patterns.
        exclusion_criteria: Frequently occurring exclusion criteria patterns.
        sample_size_stats: Descriptive statistics for enrollment counts.
        limited_evidence: True when fewer than 5 trials were analyzed.
        message: Optional descriptive message (e.g., limited evidence note).
    """

    primary_endpoints: List[EndpointPattern] = field(default_factory=list)
    secondary_endpoints: List[EndpointPattern] = field(default_factory=list)
    inclusion_criteria: List[CriteriaPattern] = field(default_factory=list)
    exclusion_criteria: List[CriteriaPattern] = field(default_factory=list)
    sample_size_stats: SampleSizeStats = field(
        default_factory=lambda: SampleSizeStats(None, None, None, 0)
    )
    limited_evidence: bool = False
    message: Optional[str] = None


@dataclass
class ProtocolOutlineResult:
    """Structured output of the generate_protocol_outline tool.

    Attributes:
        markdown: The complete Markdown-formatted Protocol_Outline document.
        citation_count: Number of unique trials cited in the outline.
        sections_with_placeholders: Names of sections that could not be
            populated due to insufficient data and contain placeholder text.
    """

    markdown: str
    citation_count: int
    sections_with_placeholders: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ClinicalTrials.gov API constants
# ---------------------------------------------------------------------------

API_URL = "https://clinicaltrials.gov/api/v2/studies"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retry attempts
TIMEOUT = 10     # seconds per request


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


@tool
def search_clinical_trials(disease_area: str, trial_phase: str) -> dict:
    """
    Search ClinicalTrials.gov for completed clinical trials matching the given
    disease area and trial phase.

    Calls the ClinicalTrials.gov API v2 endpoint and returns a structured list
    of completed trial records. Validates and normalizes inputs before querying.
    Retries up to 2 times on HTTP errors (4xx/5xx) with a 2-second delay.

    Args:
        disease_area (str): The therapeutic area or condition to search for
            (e.g., "non-small cell lung cancer", "type 2 diabetes").
            Must be between 2 and 500 characters after trimming whitespace.
        trial_phase (str): The clinical development phase. Accepted values
            (case-insensitive, spacing-tolerant): "Phase 1", "Phase 2",
            "Phase 3", "Phase 4".

    Returns:
        dict with keys:
            "trials" (list[dict]): List of trial records, each containing:
                - nct_id (str): NCT identifier (e.g., "NCT01234567")
                - title (str | None): Official trial title
                - primary_completion_date (str | None): ISO date string
                - primary_endpoints (list[str]): Primary outcome measures
                - secondary_endpoints (list[str]): Secondary outcome measures
                - eligibility_criteria (str | None): Full eligibility text
                - enrollment (int | None): Planned enrollment count
                - url (str): https://clinicaltrials.gov/study/{nct_id}
            "total_found" (int): Total results from API before truncation
            "error" (str | None): Error message if search failed

    Example:
        result = search_clinical_trials("type 2 diabetes", "Phase 3")
        # result["trials"] contains up to 20 completed trial records
    """
    # --- 1. Validate and normalize inputs ---
    try:
        validated_disease_area = validate_disease_area(disease_area)
        canonical_phase = normalize_trial_phase(trial_phase)
    except ValueError as e:
        return {"trials": [], "total_found": 0, "error": str(e)}

    # --- 2. Build query parameters ---
    params = {
        "query.cond": validated_disease_area,
        "filter.advanced": (
            f"AREA[Phase]{canonical_phase} AND AREA[OverallStatus]COMPLETED"
        ),
        "sort": "@relevance",
        "pageSize": "10",
        "format": "json",
    }

    # --- 3. Retry loop ---
    last_status_code = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(API_URL, params=params, timeout=TIMEOUT)
            if response.status_code == 200:
                break
            last_status_code = response.status_code
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            return {
                "trials": [],
                "total_found": 0,
                "error": f"Network error contacting ClinicalTrials.gov: {str(e)}",
            }
    else:
        # All attempts exhausted with HTTP errors
        return {
            "trials": [],
            "total_found": 0,
            "error": (
                f"ClinicalTrials.gov API error after {MAX_RETRIES} attempts: "
                f"HTTP {last_status_code}. Please check the disease area "
                f"spelling or try again later."
            ),
        }

    # --- 4. Parse response ---
    response_json = response.json()
    studies = response_json.get("studies", [])
    total_count = response_json.get("totalCount", len(studies))

    trial_records: List[TrialRecord] = []
    for study in studies:
        protocol = study.get("protocolSection", {})

        identification = protocol.get("identificationModule", {})
        nct_id = identification.get("nctId", None)

        # Skip records without an NCT ID — they cannot be cited
        if nct_id is None:
            continue

        title = identification.get("officialTitle", None)

        status_module = protocol.get("statusModule", {})
        primary_completion_date = (
            status_module.get("primaryCompletionDateStruct", {}).get("date", None)
        )

        outcomes_module = protocol.get("outcomesModule", {})
        primary_endpoints = [
            o.get("measure")
            for o in outcomes_module.get("primaryOutcomes", [])
            if o.get("measure")
        ]
        secondary_endpoints = [
            o.get("measure")
            for o in outcomes_module.get("secondaryOutcomes", [])
            if o.get("measure")
        ]

        eligibility_criteria_raw = (
            protocol.get("eligibilityModule", {}).get("eligibilityCriteria", None)
        )
        # Truncate to reduce LLM context size; analyze_protocols parses the full text
        eligibility_criteria = (
            eligibility_criteria_raw[:500] + "..." if eligibility_criteria_raw and len(eligibility_criteria_raw) > 500 else eligibility_criteria_raw
        )

        enrollment = (
            protocol.get("designModule", {})
            .get("enrollmentInfo", {})
            .get("count", None)
        )

        url = f"https://clinicaltrials.gov/study/{nct_id}"

        trial_records.append(
            TrialRecord(
                nct_id=nct_id,
                title=title,
                primary_completion_date=primary_completion_date,
                primary_endpoints=primary_endpoints,
                secondary_endpoints=secondary_endpoints,
                eligibility_criteria=eligibility_criteria,
                enrollment=enrollment,
                url=url,
            )
        )

    # --- 5. Sort by primary_completion_date descending (None dates sort last) ---
    def _sort_key(t: TrialRecord):
        # ISO date strings sort lexicographically in the correct order;
        # use "" so that None values sort after real dates.
        return t.primary_completion_date or ""

    sorted_trials = sorted(trial_records, key=_sort_key, reverse=True)[:20]

    # --- 6. Return structured result ---
    return {
        "trials": [vars(t) for t in sorted_trials],
        "total_found": total_count,
        "error": None,
    }


@tool
def analyze_protocols(trials: list) -> dict:
    """
    Analyze a list of clinical trial records to identify common patterns in
    endpoints, eligibility criteria, and sample sizes.

    Computes frequency distributions for primary endpoints, secondary endpoints,
    inclusion criteria, and exclusion criteria. Applies a 30% frequency threshold
    (reduced to 20% when fewer than 5 trials are provided). Calculates descriptive
    statistics (median, min, max) for enrollment counts.

    Args:
        trials (list[dict]): List of trial records as returned by
            search_clinical_trials. Each record must contain the fields
            defined in the search_clinical_trials return schema.
            An empty list is accepted and returns an empty analysis object.

    Returns:
        dict with keys:
            "primary_endpoints" (list[dict]): Each item has:
                - "text" (str): Endpoint description
                - "frequency" (int): Number of trials containing this endpoint
                - "nct_ids" (list[str]): NCT identifiers of supporting trials
            "secondary_endpoints" (list[dict]): Same structure as primary_endpoints
            "inclusion_criteria" (list[dict]): Each item has:
                - "pattern" (str): Criteria pattern description
                - "frequency" (int): Number of trials containing this pattern
                - "nct_ids" (list[str]): NCT identifiers of supporting trials
            "exclusion_criteria" (list[dict]): Same structure as inclusion_criteria
            "sample_size_stats" (dict):
                - "median" (float | None)
                - "minimum" (int | None)
                - "maximum" (int | None)
                - "count" (int): Number of trials with enrollment data
            "limited_evidence" (bool): True when fewer than 5 trials were analyzed
            "message" (str | None): Descriptive message (e.g., limited evidence note)

    Example:
        analysis = analyze_protocols(trials)
        # analysis["primary_endpoints"][0]["nct_ids"] lists supporting trials
    """
    import math

    # --- 1. Empty input ---
    if len(trials) == 0:
        return {
            "primary_endpoints": [],
            "secondary_endpoints": [],
            "inclusion_criteria": [],
            "exclusion_criteria": [],
            "sample_size_stats": {
                "median": None,
                "minimum": None,
                "maximum": None,
                "count": 0,
            },
            "limited_evidence": False,
            "message": "No trial records provided for analysis.",
        }

    # --- 2. Frequency threshold ---
    N = len(trials)
    limited_evidence = N < 5
    threshold = math.ceil(0.20 * N) if limited_evidence else math.ceil(0.30 * N)

    # --- 3. Endpoint frequency analysis helper ---
    def _analyze_endpoints(endpoint_key: str) -> list:
        """Build frequency dict for a list-of-strings field on each trial."""
        freq: dict = {}  # text -> {"frequency": int, "nct_ids": list[str]}
        for trial in trials:
            nct_id = trial.get("nct_id", "")
            for endpoint in trial.get(endpoint_key, []):
                normalized = endpoint.strip()
                if not normalized:
                    continue
                if normalized not in freq:
                    freq[normalized] = {"frequency": 0, "nct_ids": []}
                freq[normalized]["frequency"] += 1
                freq[normalized]["nct_ids"].append(nct_id)
        # Filter by threshold and sort descending by frequency
        result = [
            {"text": text, "frequency": data["frequency"], "nct_ids": data["nct_ids"]}
            for text, data in freq.items()
            if data["frequency"] >= threshold
        ]
        result.sort(key=lambda x: x["frequency"], reverse=True)
        return result

    # --- 4. Eligibility criteria parsing helper ---
    def _parse_criteria_section(text: str, section: str) -> list:
        """
        Extract individual criteria lines from a named section of eligibility text.

        Splits the full eligibility text on "Inclusion Criteria:" and
        "Exclusion Criteria:" headers (case-insensitive), then splits the
        relevant section into individual lines.
        """
        if not text:
            return []

        import re

        # Split on both headers to isolate sections
        inclusion_pattern = re.compile(r"inclusion\s+criteria\s*:", re.IGNORECASE)
        exclusion_pattern = re.compile(r"exclusion\s+criteria\s*:", re.IGNORECASE)

        inclusion_match = inclusion_pattern.search(text)
        exclusion_match = exclusion_pattern.search(text)

        if section == "inclusion":
            if not inclusion_match:
                return []
            start = inclusion_match.end()
            end = exclusion_match.start() if exclusion_match and exclusion_match.start() > start else len(text)
            section_text = text[start:end]
        else:  # exclusion
            if not exclusion_match:
                return []
            start = exclusion_match.end()
            # If there's another inclusion section after exclusion, stop there
            next_inclusion = inclusion_pattern.search(text, start)
            end = next_inclusion.start() if next_inclusion else len(text)
            section_text = text[start:end]

        # Split into lines, strip, skip empty lines and header-like lines
        lines = []
        for line in section_text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            # Skip lines that look like section headers
            if inclusion_pattern.match(stripped) or exclusion_pattern.match(stripped):
                continue
            lines.append(stripped)
        return lines

    def _analyze_criteria(section: str) -> list:
        """Build frequency dict for inclusion or exclusion criteria patterns."""
        freq: dict = {}  # normalized_text -> {"display": str, "frequency": int, "nct_ids": list[str]}
        for trial in trials:
            nct_id = trial.get("nct_id", "")
            eligibility_text = trial.get("eligibility_criteria") or ""
            criteria_lines = _parse_criteria_section(eligibility_text, section)
            # Deduplicate within a single trial to avoid double-counting
            seen_in_trial: set = set()
            for line in criteria_lines:
                normalized = line.strip().lower()
                if not normalized or normalized in seen_in_trial:
                    continue
                seen_in_trial.add(normalized)
                if normalized not in freq:
                    freq[normalized] = {"display": line.strip(), "frequency": 0, "nct_ids": []}
                freq[normalized]["frequency"] += 1
                freq[normalized]["nct_ids"].append(nct_id)
        # Filter by threshold and sort descending by frequency
        result = [
            {
                "pattern": data["display"],
                "frequency": data["frequency"],
                "nct_ids": data["nct_ids"],
            }
            for normalized, data in freq.items()
            if data["frequency"] >= threshold
        ]
        result.sort(key=lambda x: x["frequency"], reverse=True)
        return result

    # --- 5. Sample size stats ---
    enrollments = [t["enrollment"] for t in trials if t.get("enrollment") is not None]
    if not enrollments:
        sample_size_stats = {"median": None, "minimum": None, "maximum": None, "count": 0}
    else:
        sample_size_stats = {
            "median": statistics.median(enrollments),
            "minimum": min(enrollments),
            "maximum": max(enrollments),
            "count": len(enrollments),
        }

    # --- 6. Build and return result ---
    message = (
        "Limited evidence base: fewer than 5 trials analyzed. Frequency threshold reduced to 20%."
        if limited_evidence
        else None
    )

    return {
        "primary_endpoints": _analyze_endpoints("primary_endpoints"),
        "secondary_endpoints": _analyze_endpoints("secondary_endpoints"),
        "inclusion_criteria": _analyze_criteria("inclusion"),
        "exclusion_criteria": _analyze_criteria("exclusion"),
        "sample_size_stats": sample_size_stats,
        "limited_evidence": limited_evidence,
        "message": message,
    }


@tool
def generate_protocol_outline(
    analysis: dict,
    disease_area: str,
    trial_phase: str,
) -> dict:
    """
    Generate a structured draft protocol outline in Markdown format based on
    the analysis of completed clinical trials.

    Produces a Protocol_Outline with seven sections: Study Objectives, Primary
    Endpoints, Secondary Endpoints, Inclusion Criteria, Exclusion Criteria,
    Sample Size Guidance, and Study Design Considerations. Each recommendation
    includes evidence-based rationale and inline citation identifiers. A
    References section lists all cited trials with NCT ID, title, completion
    date, and URL. Citation consistency is validated before returning.

    Args:
        analysis (dict): Structured analysis object as returned by
            analyze_protocols.
        disease_area (str): The disease area used in the original search
            (used for section headers and study objectives).
        trial_phase (str): The trial phase used in the original search
            (used for section headers and study design context).

    Returns:
        dict with keys:
            "markdown" (str): The complete Markdown-formatted Protocol_Outline.
            "citation_count" (int): Number of unique trials cited.
            "sections_with_placeholders" (list[str]): Names of sections that
                could not be populated due to insufficient data.

    Example:
        result = generate_protocol_outline(analysis, "type 2 diabetes", "Phase 3")
        print(result["markdown"])
    """
    import re

    # -----------------------------------------------------------------------
    # Step 1: Build citation registry
    # -----------------------------------------------------------------------
    all_nct_ids = set()
    for ep in analysis.get("primary_endpoints", []):
        all_nct_ids.update(ep.get("nct_ids", []))
    for ep in analysis.get("secondary_endpoints", []):
        all_nct_ids.update(ep.get("nct_ids", []))
    for cp in analysis.get("inclusion_criteria", []):
        all_nct_ids.update(cp.get("nct_ids", []))
    for cp in analysis.get("exclusion_criteria", []):
        all_nct_ids.update(cp.get("nct_ids", []))

    # Sort for determinism
    sorted_nct_ids = sorted(all_nct_ids)
    # citation_map: nct_id -> citation number (1-indexed)
    citation_map = {nct_id: i + 1 for i, nct_id in enumerate(sorted_nct_ids)}

    # -----------------------------------------------------------------------
    # Step 2: Helper to format inline citations
    # -----------------------------------------------------------------------
    def _format_citations(nct_ids: list) -> str:
        """Return inline citation string like '[1][2][3]' or 'supported by N trials [1][2]...'"""
        if not nct_ids:
            return ""
        citation_nums = sorted(set(citation_map.get(nid, 0) for nid in nct_ids if nid in citation_map))
        if len(citation_nums) >= 5:
            inline = "".join(f"[{n}]" for n in citation_nums)
            return f" *(supported by {len(citation_nums)} trials {inline})*"
        else:
            return " " + "".join(f"[{n}]" for n in citation_nums)

    # -----------------------------------------------------------------------
    # Step 3: Build each section
    # -----------------------------------------------------------------------
    sections_with_placeholders = []
    cited_nct_ids = set()

    # --- Section 1: Study Objectives (always generated) ---
    section_1 = f"""## 1. Study Objectives

This {trial_phase} clinical trial protocol targets **{disease_area}**.

**Primary Objective:** To evaluate the efficacy and safety of the investigational
intervention in patients with {disease_area}.

**Secondary Objective:** To characterize the pharmacokinetic and pharmacodynamic
profile of the investigational intervention in the target population.
"""

    # --- Section 2: Primary Endpoints ---
    primary_endpoints = analysis.get("primary_endpoints", [])
    if primary_endpoints:
        lines = ["## 2. Primary Endpoints", ""]
        for i, ep in enumerate(primary_endpoints, 1):
            text = ep.get("text", "")
            frequency = ep.get("frequency", 0)
            nct_ids = ep.get("nct_ids", [])
            cited_nct_ids.update(nct_ids)
            citation_str = _format_citations(nct_ids)
            lines.append(f"{i}. {text}{citation_str}")
            lines.append(f"   *Observed in {frequency} of the analyzed source trials.*")
            lines.append("")
        section_2 = "\n".join(lines)
    else:
        sections_with_placeholders.append("Primary Endpoints")
        section_2 = """## 2. Primary Endpoints

*[Data gap: No primary endpoint patterns were identified in the analyzed trials.
Consider broadening the disease area or reviewing the source trials manually.]*
"""

    # --- Section 3: Secondary Endpoints ---
    secondary_endpoints = analysis.get("secondary_endpoints", [])
    if secondary_endpoints:
        lines = ["## 3. Secondary Endpoints", ""]
        for i, ep in enumerate(secondary_endpoints, 1):
            text = ep.get("text", "")
            frequency = ep.get("frequency", 0)
            nct_ids = ep.get("nct_ids", [])
            cited_nct_ids.update(nct_ids)
            citation_str = _format_citations(nct_ids)
            lines.append(f"{i}. {text}{citation_str}")
            lines.append(f"   *Observed in {frequency} of the analyzed source trials.*")
            lines.append("")
        section_3 = "\n".join(lines)
    else:
        sections_with_placeholders.append("Secondary Endpoints")
        section_3 = """## 3. Secondary Endpoints

*[Data gap: No secondary endpoint patterns were identified in the analyzed trials.
Consider broadening the disease area or reviewing the source trials manually.]*
"""

    # --- Section 4: Inclusion Criteria ---
    inclusion_criteria = analysis.get("inclusion_criteria", [])
    if inclusion_criteria:
        lines = ["## 4. Inclusion Criteria", ""]
        for i, cp in enumerate(inclusion_criteria, 1):
            pattern = cp.get("pattern", "")
            frequency = cp.get("frequency", 0)
            nct_ids = cp.get("nct_ids", [])
            cited_nct_ids.update(nct_ids)
            citation_str = _format_citations(nct_ids)
            lines.append(f"{i}. {pattern}{citation_str}")
            lines.append(f"   *Present in {frequency} of the analyzed source trials.*")
            lines.append("")
        section_4 = "\n".join(lines)
    else:
        sections_with_placeholders.append("Inclusion Criteria")
        section_4 = """## 4. Inclusion Criteria

*[Data gap: No inclusion criteria patterns were identified in the analyzed trials.
Consider broadening the disease area or reviewing the source trials manually.]*
"""

    # --- Section 5: Exclusion Criteria ---
    exclusion_criteria = analysis.get("exclusion_criteria", [])
    if exclusion_criteria:
        lines = ["## 5. Exclusion Criteria", ""]
        for i, cp in enumerate(exclusion_criteria, 1):
            pattern = cp.get("pattern", "")
            frequency = cp.get("frequency", 0)
            nct_ids = cp.get("nct_ids", [])
            cited_nct_ids.update(nct_ids)
            citation_str = _format_citations(nct_ids)
            lines.append(f"{i}. {pattern}{citation_str}")
            lines.append(f"   *Present in {frequency} of the analyzed source trials.*")
            lines.append("")
        section_5 = "\n".join(lines)
    else:
        sections_with_placeholders.append("Exclusion Criteria")
        section_5 = """## 5. Exclusion Criteria

*[Data gap: No exclusion criteria patterns were identified in the analyzed trials.
Consider broadening the disease area or reviewing the source trials manually.]*
"""

    # --- Section 6: Sample Size Guidance ---
    stats = analysis.get("sample_size_stats", {})
    median = stats.get("median")
    minimum = stats.get("minimum")
    maximum = stats.get("maximum")
    count = stats.get("count", 0)

    if median is not None:
        section_6 = f"""## 6. Sample Size Guidance

Based on analysis of {count} source trial(s) with enrollment data:

- **Recommended enrollment:** {int(median)} participants (median of source trials)
- **Observed range:** {minimum} to {maximum} participants across source trials

*Note: Final sample size should be determined by a formal power calculation
based on the primary endpoint effect size and desired statistical power.*
"""
    else:
        sections_with_placeholders.append("Sample Size Guidance")
        section_6 = """## 6. Sample Size Guidance

*[Data gap: No enrollment data was available in the analyzed trials.
Sample size should be determined by a formal power calculation based on
the primary endpoint effect size and desired statistical power.]*
"""

    # --- Section 7: Study Design Considerations (always generated) ---
    section_7 = f"""## 7. Study Design Considerations

- **Phase:** {trial_phase}
- **Design:** Randomized, double-blind, placebo-controlled (recommended for {trial_phase})
- **Population:** Adult patients (≥18 years) diagnosed with {disease_area}
- **Duration:** To be determined based on primary endpoint measurement timeframe
- **Randomization:** 1:1 allocation ratio (intervention vs. control)
- **Blinding:** Double-blind with independent data monitoring committee
"""

    # -----------------------------------------------------------------------
    # Step 4: Build References section
    # -----------------------------------------------------------------------
    ref_lines = ["## References", ""]
    for nct_id in sorted_nct_ids:
        if nct_id in cited_nct_ids:
            citation_num = citation_map[nct_id]
            url = f"https://clinicaltrials.gov/study/{nct_id}"
            ref_lines.append(f"[{citation_num}] {nct_id}. ClinicalTrials.gov. {url}")
    references_section = "\n".join(ref_lines)

    # -----------------------------------------------------------------------
    # Step 5: Assemble full markdown (before self-healing)
    # -----------------------------------------------------------------------
    title = f"# Protocol Outline: {disease_area} — {trial_phase}\n"
    body = "\n".join([
        title,
        section_1,
        section_2,
        section_3,
        section_4,
        section_5,
        section_6,
        section_7,
        references_section,
    ])

    # -----------------------------------------------------------------------
    # Step 5: Citation consistency self-healing
    # -----------------------------------------------------------------------
    # Split body from references for targeted parsing
    ref_header_match = re.search(r"^## References", body, re.MULTILINE)
    if ref_header_match:
        body_text = body[: ref_header_match.start()]
        ref_text = body[ref_header_match.start():]
    else:
        body_text = body
        ref_text = "## References\n"

    # Parse all [N] in body
    body_citation_nums = set(int(m) for m in re.findall(r"\[(\d+)\]", body_text))

    # Parse all citation numbers defined in References
    ref_citation_nums = set(int(m) for m in re.findall(r"^\[(\d+)\]", ref_text, re.MULTILINE))

    # For any [N] in body with no References entry: add a placeholder reference
    missing_in_refs = body_citation_nums - ref_citation_nums
    if missing_in_refs:
        extra_lines = []
        for num in sorted(missing_in_refs):
            # Find the nct_id for this citation number (reverse lookup)
            nct_id_for_num = next(
                (nid for nid, n in citation_map.items() if n == num), f"UNKNOWN-{num}"
            )
            url = f"https://clinicaltrials.gov/study/{nct_id_for_num}"
            extra_lines.append(f"[{num}] {nct_id_for_num}. ClinicalTrials.gov. {url}")
        ref_text = ref_text.rstrip() + "\n" + "\n".join(extra_lines) + "\n"

    # For any References entry with no [N] in body: remove it
    orphan_in_refs = ref_citation_nums - body_citation_nums
    if orphan_in_refs:
        ref_lines_list = ref_text.split("\n")
        filtered = [
            line for line in ref_lines_list
            if not re.match(r"^\[(\d+)\]", line) or
            int(re.match(r"^\[(\d+)\]", line).group(1)) not in orphan_in_refs
        ]
        ref_text = "\n".join(filtered)

    full_markdown = body_text + ref_text

    # -----------------------------------------------------------------------
    # Step 6: Return result
    # -----------------------------------------------------------------------
    return {
        "markdown": full_markdown,
        "citation_count": len(cited_nct_ids),
        "sections_with_placeholders": sections_with_placeholders,
    }
