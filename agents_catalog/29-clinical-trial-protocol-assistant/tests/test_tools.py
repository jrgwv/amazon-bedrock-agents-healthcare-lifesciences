"""
Unit tests for the Clinical Trial Protocol Assistant tools.

Tests cover:
  - search_clinical_trials: valid inputs, HTTP errors with retry, zero results
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Path setup — allow imports from the agent package without installing it
# ---------------------------------------------------------------------------
_AGENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "agent"
)
sys.path.insert(0, os.path.abspath(_AGENT_DIR))

# ---------------------------------------------------------------------------
# Stub out the `strands` package if it is not installed in this environment.
# The @tool decorator is a no-op for testing purposes — we only need the
# function's logic, not the Strands agent-loop integration.
# ---------------------------------------------------------------------------
if "strands" not in sys.modules:
    _strands_stub = MagicMock()
    # Make @tool act as a pass-through decorator
    _strands_stub.tool = lambda fn: fn
    sys.modules["strands"] = _strands_stub

from agent_config.tools.clinical_trials_tools import search_clinical_trials  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_study(nct_id: str, title: str = "A Study", date: str = "2022-01-01") -> dict:
    """Return a minimal ClinicalTrials.gov API v2 study dict."""
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": nct_id,
                "officialTitle": title,
            },
            "statusModule": {
                "primaryCompletionDateStruct": {"date": date},
            },
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Overall Survival"}],
                "secondaryOutcomes": [{"measure": "Progression-Free Survival"}],
            },
            "eligibilityModule": {
                "eligibilityCriteria": "Inclusion: Age >= 18\nExclusion: Pregnancy",
            },
            "designModule": {
                "enrollmentInfo": {"count": 200},
            },
        }
    }


def _make_api_response(n: int, total=None) -> dict:
    """Return a mock API JSON response with *n* studies."""
    studies = [_make_study(f"NCT{i:08d}", date=f"202{i % 3}-0{(i % 9) + 1}-01") for i in range(1, n + 1)]
    return {
        "studies": studies,
        "totalCount": total if total is not None else n,
    }


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    return mock


# ---------------------------------------------------------------------------
# Tests: search_clinical_trials
# ---------------------------------------------------------------------------

class TestSearchClinicalTrials(unittest.TestCase):

    # ------------------------------------------------------------------
    # Valid inputs — 10-result API response
    # ------------------------------------------------------------------

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_valid_inputs_returns_10_records(self, mock_get):
        """Valid inputs with mocked 10-result API response → 10 records returned."""
        mock_get.return_value = _mock_response(_make_api_response(10))

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        self.assertIsNone(result["error"])
        self.assertEqual(len(result["trials"]), 10)
        self.assertEqual(result["total_found"], 10)

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_trial_record_fields_are_populated(self, mock_get):
        """Each returned trial record contains all expected fields."""
        mock_get.return_value = _mock_response(_make_api_response(1))

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        trial = result["trials"][0]
        self.assertIn("nct_id", trial)
        self.assertIn("title", trial)
        self.assertIn("primary_completion_date", trial)
        self.assertIn("primary_endpoints", trial)
        self.assertIn("secondary_endpoints", trial)
        self.assertIn("eligibility_criteria", trial)
        self.assertIn("enrollment", trial)
        self.assertIn("url", trial)

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_url_format(self, mock_get):
        """URL field follows the canonical https://clinicaltrials.gov/study/{nct_id} format."""
        mock_get.return_value = _mock_response(_make_api_response(1))

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        trial = result["trials"][0]
        self.assertEqual(trial["url"], f"https://clinicaltrials.gov/study/{trial['nct_id']}")

    # ------------------------------------------------------------------
    # HTTP 500 → retries, returns error dict
    # ------------------------------------------------------------------

    @patch("agent_config.tools.clinical_trials_tools.time.sleep")
    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_http_500_retries_and_returns_error(self, mock_get, mock_sleep):
        """Mocked HTTP 500 → retries 2 times, returns error dict after 3rd failure."""
        mock_get.return_value = _mock_response({}, status_code=500)

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        # Should have attempted MAX_RETRIES (3) times
        self.assertEqual(mock_get.call_count, 3)
        # Should have slept between retries (MAX_RETRIES - 1 = 2 sleeps)
        self.assertEqual(mock_sleep.call_count, 2)
        # Result should be an error dict
        self.assertEqual(result["trials"], [])
        self.assertEqual(result["total_found"], 0)
        self.assertIsNotNone(result["error"])
        self.assertIn("500", result["error"])

    @patch("agent_config.tools.clinical_trials_tools.time.sleep")
    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_http_500_then_200_succeeds(self, mock_get, mock_sleep):
        """Mocked HTTP 500 then 200 → succeeds on second attempt."""
        mock_get.side_effect = [
            _mock_response({}, status_code=500),
            _mock_response(_make_api_response(5)),
        ]

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        self.assertEqual(mock_get.call_count, 2)
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["trials"]), 5)

    # ------------------------------------------------------------------
    # Zero-result response
    # ------------------------------------------------------------------

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_zero_results_returns_empty_trials_no_error(self, mock_get):
        """Mocked 0-result response → returns empty trials list with no error."""
        mock_get.return_value = _mock_response({"studies": [], "totalCount": 0})

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        self.assertEqual(result["trials"], [])
        self.assertEqual(result["total_found"], 0)
        self.assertIsNone(result["error"])

    # ------------------------------------------------------------------
    # Input validation errors
    # ------------------------------------------------------------------

    def test_invalid_disease_area_too_short(self):
        """Disease area shorter than 2 chars → error dict, no HTTP call."""
        result = search_clinical_trials("x", "Phase 3")

        self.assertEqual(result["trials"], [])
        self.assertEqual(result["total_found"], 0)
        self.assertIsNotNone(result["error"])

    def test_invalid_trial_phase(self):
        """Unrecognized trial phase → error dict, no HTTP call."""
        result = search_clinical_trials("type 2 diabetes", "Phase 5")

        self.assertEqual(result["trials"], [])
        self.assertEqual(result["total_found"], 0)
        self.assertIsNotNone(result["error"])

    # ------------------------------------------------------------------
    # Missing fields → null substitution
    # ------------------------------------------------------------------

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_missing_fields_substituted_with_none(self, mock_get):
        """API response with missing optional fields → None substitution, no exception."""
        minimal_study = {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00000001"},
                # All other modules intentionally absent
            }
        }
        mock_get.return_value = _mock_response({"studies": [minimal_study], "totalCount": 1})

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        self.assertIsNone(result["error"])
        self.assertEqual(len(result["trials"]), 1)
        trial = result["trials"][0]
        self.assertIsNone(trial["title"])
        self.assertIsNone(trial["primary_completion_date"])
        self.assertEqual(trial["primary_endpoints"], [])
        self.assertEqual(trial["secondary_endpoints"], [])
        self.assertIsNone(trial["eligibility_criteria"])
        self.assertIsNone(trial["enrollment"])

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_study_without_nct_id_is_skipped(self, mock_get):
        """Studies missing nct_id are skipped; valid studies are still returned."""
        studies = [
            {"protocolSection": {"identificationModule": {}}},  # no nctId
            _make_study("NCT00000002"),
        ]
        mock_get.return_value = _mock_response({"studies": studies, "totalCount": 2})

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        self.assertIsNone(result["error"])
        self.assertEqual(len(result["trials"]), 1)
        self.assertEqual(result["trials"][0]["nct_id"], "NCT00000002")

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_results_sorted_by_date_descending(self, mock_get):
        """Results are sorted by primary_completion_date descending."""
        studies = [
            _make_study("NCT00000001", date="2020-01-01"),
            _make_study("NCT00000003", date="2022-06-15"),
            _make_study("NCT00000002", date="2021-03-10"),
        ]
        mock_get.return_value = _mock_response({"studies": studies, "totalCount": 3})

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        dates = [t["primary_completion_date"] for t in result["trials"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    @patch("agent_config.tools.clinical_trials_tools.requests.get")
    def test_none_dates_sort_last(self, mock_get):
        """Trials with None primary_completion_date sort after trials with dates."""
        studies = [
            _make_study("NCT00000001", date="2020-01-01"),
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000002"},
                    "statusModule": {},  # no primaryCompletionDateStruct
                    "outcomesModule": {},
                    "eligibilityModule": {},
                    "designModule": {},
                }
            },
            _make_study("NCT00000003", date="2022-06-15"),
        ]
        mock_get.return_value = _mock_response({"studies": studies, "totalCount": 3})

        result = search_clinical_trials("type 2 diabetes", "Phase 3")

        # The trial with None date should be last
        self.assertIsNone(result["trials"][-1]["primary_completion_date"])


if __name__ == "__main__":
    unittest.main()


from agent_config.tools.clinical_trials_tools import analyze_protocols  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers for analyze_protocols tests
# ---------------------------------------------------------------------------

def _make_trial(
    nct_id: str,
    primary_endpoints: list = None,
    secondary_endpoints: list = None,
    eligibility_criteria: str = None,
    enrollment: int = None,
) -> dict:
    """Return a minimal trial dict suitable for analyze_protocols."""
    return {
        "nct_id": nct_id,
        "title": "A Study",
        "primary_completion_date": "2022-01-01",
        "primary_endpoints": primary_endpoints or [],
        "secondary_endpoints": secondary_endpoints or [],
        "eligibility_criteria": eligibility_criteria,
        "enrollment": enrollment,
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
    }


# ---------------------------------------------------------------------------
# Tests: analyze_protocols
# ---------------------------------------------------------------------------

class TestAnalyzeProtocols(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. Empty list
    # ------------------------------------------------------------------

    def test_empty_list_returns_empty_analysis(self):
        """Empty list → all lists empty, message set, no exception."""
        result = analyze_protocols([])

        self.assertEqual(result["primary_endpoints"], [])
        self.assertEqual(result["secondary_endpoints"], [])
        self.assertEqual(result["inclusion_criteria"], [])
        self.assertEqual(result["exclusion_criteria"], [])
        self.assertEqual(result["sample_size_stats"]["count"], 0)
        self.assertIsNone(result["sample_size_stats"]["median"])
        self.assertIsNotNone(result["message"])
        self.assertFalse(result["limited_evidence"])

    # ------------------------------------------------------------------
    # 2. limited_evidence flag for < 5 trials
    # ------------------------------------------------------------------

    def test_limited_evidence_flag_set_for_fewer_than_5_trials(self):
        """3 trials → limited_evidence = True."""
        trials = [_make_trial(f"NCT{i:08d}") for i in range(3)]
        result = analyze_protocols(trials)
        self.assertTrue(result["limited_evidence"])

    def test_limited_evidence_flag_not_set_for_5_or_more_trials(self):
        """5 trials → limited_evidence = False."""
        trials = [_make_trial(f"NCT{i:08d}") for i in range(5)]
        result = analyze_protocols(trials)
        self.assertFalse(result["limited_evidence"])

    # ------------------------------------------------------------------
    # 3. 30% threshold for >= 5 trials
    # ------------------------------------------------------------------

    def test_frequency_threshold_30_percent_for_5_or_more_trials(self):
        """10 trials: 3 share endpoint A (30%, at threshold → included),
        2 share endpoint B (20%, below threshold → excluded)."""
        # ceil(0.30 * 10) = 3
        trials = []
        for i in range(10):
            endpoints = []
            if i < 3:
                endpoints.append("Endpoint A")
            if i < 2:
                endpoints.append("Endpoint B")
            trials.append(_make_trial(f"NCT{i:08d}", primary_endpoints=endpoints))

        result = analyze_protocols(trials)
        texts = [ep["text"] for ep in result["primary_endpoints"]]

        self.assertIn("Endpoint A", texts)
        self.assertNotIn("Endpoint B", texts)

    # ------------------------------------------------------------------
    # 4. 20% threshold for < 5 trials
    # ------------------------------------------------------------------

    def test_frequency_threshold_20_percent_for_fewer_than_5_trials(self):
        """4 trials: 1 shares an endpoint (1/4 = 25%, above 20% threshold → included)."""
        # ceil(0.20 * 4) = 1
        trials = [
            _make_trial("NCT00000001", primary_endpoints=["Shared Endpoint"]),
            _make_trial("NCT00000002"),
            _make_trial("NCT00000003"),
            _make_trial("NCT00000004"),
        ]
        result = analyze_protocols(trials)
        texts = [ep["text"] for ep in result["primary_endpoints"]]
        self.assertIn("Shared Endpoint", texts)

    # ------------------------------------------------------------------
    # 5. Sample size stats correct
    # ------------------------------------------------------------------

    def test_sample_size_stats_correct(self):
        """Trials with enrollments [100, 200, 300] → median=200.0, min=100, max=300, count=3."""
        trials = [
            _make_trial("NCT00000001", enrollment=100),
            _make_trial("NCT00000002", enrollment=200),
            _make_trial("NCT00000003", enrollment=300),
        ]
        result = analyze_protocols(trials)
        stats = result["sample_size_stats"]

        self.assertEqual(stats["median"], 200.0)
        self.assertEqual(stats["minimum"], 100)
        self.assertEqual(stats["maximum"], 300)
        self.assertEqual(stats["count"], 3)

    # ------------------------------------------------------------------
    # 6. None enrollment excluded from stats
    # ------------------------------------------------------------------

    def test_none_enrollment_excluded_from_stats(self):
        """Mix of None and int enrollments → count reflects only non-None values."""
        trials = [
            _make_trial("NCT00000001", enrollment=100),
            _make_trial("NCT00000002", enrollment=None),
            _make_trial("NCT00000003", enrollment=300),
            _make_trial("NCT00000004", enrollment=None),
        ]
        result = analyze_protocols(trials)
        stats = result["sample_size_stats"]

        self.assertEqual(stats["count"], 2)
        self.assertIsNotNone(stats["median"])
        self.assertEqual(stats["minimum"], 100)
        self.assertEqual(stats["maximum"], 300)

    # ------------------------------------------------------------------
    # 7. Endpoint nct_ids attribution
    # ------------------------------------------------------------------

    def test_endpoint_nct_ids_attribution(self):
        """nct_ids in returned patterns match exactly the trials containing that endpoint."""
        # Use 10 trials so threshold = ceil(0.30 * 10) = 3
        # Trials 0,1,2 share "Overall Survival"; trials 3-9 do not
        trials = []
        for i in range(10):
            ep = ["Overall Survival"] if i < 3 else []
            trials.append(_make_trial(f"NCT{i:08d}", primary_endpoints=ep))

        result = analyze_protocols(trials)
        ep_map = {ep["text"]: ep["nct_ids"] for ep in result["primary_endpoints"]}

        self.assertIn("Overall Survival", ep_map)
        expected_ids = {f"NCT{i:08d}" for i in range(3)}
        self.assertEqual(set(ep_map["Overall Survival"]), expected_ids)

    # ------------------------------------------------------------------
    # 8. Results sorted descending by frequency
    # ------------------------------------------------------------------

    def test_results_sorted_descending_by_frequency(self):
        """primary_endpoints list is sorted by frequency descending."""
        # Use 10 trials: endpoint A appears 3 times, endpoint B appears 4 times
        # ceil(0.30 * 10) = 3, so both qualify
        trials = []
        for i in range(10):
            endpoints = []
            if i < 4:
                endpoints.append("Endpoint B")  # frequency 4
            if i < 3:
                endpoints.append("Endpoint A")  # frequency 3
            trials.append(_make_trial(f"NCT{i:08d}", primary_endpoints=endpoints))

        result = analyze_protocols(trials)
        frequencies = [ep["frequency"] for ep in result["primary_endpoints"]]

        self.assertEqual(frequencies, sorted(frequencies, reverse=True))
        # Endpoint B (freq 4) should come before Endpoint A (freq 3)
        texts = [ep["text"] for ep in result["primary_endpoints"]]
        self.assertLess(texts.index("Endpoint B"), texts.index("Endpoint A"))


if __name__ == "__main__":
    unittest.main()


from agent_config.tools.clinical_trials_tools import generate_protocol_outline  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers for generate_protocol_outline tests
# ---------------------------------------------------------------------------

def _make_analysis(
    primary_endpoints=None,
    secondary_endpoints=None,
    inclusion_criteria=None,
    exclusion_criteria=None,
    median=200.0, minimum=100, maximum=300, count=3,
    limited_evidence=False,
    message=None,
):
    return {
        "primary_endpoints": primary_endpoints or [],
        "secondary_endpoints": secondary_endpoints or [],
        "inclusion_criteria": inclusion_criteria or [],
        "exclusion_criteria": exclusion_criteria or [],
        "sample_size_stats": {
            "median": median,
            "minimum": minimum,
            "maximum": maximum,
            "count": count,
        },
        "limited_evidence": limited_evidence,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Tests: generate_protocol_outline
# ---------------------------------------------------------------------------

class TestGenerateProtocolOutline(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. Valid analysis contains all section headers
    # ------------------------------------------------------------------

    def test_valid_analysis_contains_all_section_headers(self):
        """Valid analysis → output contains all 7 section headers + References."""
        analysis = _make_analysis(
            primary_endpoints=[{"text": "Overall Survival", "frequency": 3, "nct_ids": ["NCT00000001"]}],
            secondary_endpoints=[{"text": "Progression-Free Survival", "frequency": 2, "nct_ids": ["NCT00000002"]}],
            inclusion_criteria=[{"pattern": "Age >= 18 years", "frequency": 3, "nct_ids": ["NCT00000001"]}],
            exclusion_criteria=[{"pattern": "Prior chemotherapy", "frequency": 2, "nct_ids": ["NCT00000002"]}],
        )
        result = generate_protocol_outline(analysis, "type 2 diabetes", "Phase 3")
        md = result["markdown"]

        self.assertIn("Study Objectives", md)
        self.assertIn("Primary Endpoints", md)
        self.assertIn("Secondary Endpoints", md)
        self.assertIn("Inclusion Criteria", md)
        self.assertIn("Exclusion Criteria", md)
        self.assertIn("Sample Size Guidance", md)
        self.assertIn("Study Design Considerations", md)
        self.assertIn("References", md)

    # ------------------------------------------------------------------
    # 2. Empty analysis has placeholders
    # ------------------------------------------------------------------

    def test_empty_analysis_has_placeholders(self):
        """Empty analysis (no endpoints/criteria, no enrollment) → sections_with_placeholders is non-empty."""
        analysis = _make_analysis(
            primary_endpoints=[],
            secondary_endpoints=[],
            inclusion_criteria=[],
            exclusion_criteria=[],
            median=None,
            minimum=None,
            maximum=None,
            count=0,
        )
        result = generate_protocol_outline(analysis, "lung cancer", "Phase 2")
        self.assertTrue(len(result["sections_with_placeholders"]) > 0)

    # ------------------------------------------------------------------
    # 3. No primary endpoints adds placeholder
    # ------------------------------------------------------------------

    def test_no_primary_endpoints_adds_placeholder(self):
        """Analysis with no primary endpoints → 'Primary Endpoints' in sections_with_placeholders."""
        analysis = _make_analysis(primary_endpoints=[])
        result = generate_protocol_outline(analysis, "type 2 diabetes", "Phase 3")
        self.assertIn("Primary Endpoints", result["sections_with_placeholders"])

    # ------------------------------------------------------------------
    # 4. Sample size guidance contains median and range
    # ------------------------------------------------------------------

    def test_sample_size_guidance_contains_median_and_range(self):
        """Analysis with median=200, min=100, max=300 → '200', '100', '300' all appear in markdown."""
        analysis = _make_analysis(median=200.0, minimum=100, maximum=300, count=3)
        result = generate_protocol_outline(analysis, "type 2 diabetes", "Phase 3")
        md = result["markdown"]

        self.assertIn("200", md)
        self.assertIn("100", md)
        self.assertIn("300", md)

    # ------------------------------------------------------------------
    # 5. Determinism
    # ------------------------------------------------------------------

    def test_determinism(self):
        """Same input called twice → identical markdown output."""
        analysis = _make_analysis(
            primary_endpoints=[
                {"text": "Overall Survival", "frequency": 3, "nct_ids": ["NCT00000003", "NCT00000001"]},
            ],
            secondary_endpoints=[
                {"text": "Quality of Life", "frequency": 2, "nct_ids": ["NCT00000002"]},
            ],
            inclusion_criteria=[
                {"pattern": "Age >= 18 years", "frequency": 3, "nct_ids": ["NCT00000001", "NCT00000003"]},
            ],
        )
        result1 = generate_protocol_outline(analysis, "breast cancer", "Phase 2")
        result2 = generate_protocol_outline(analysis, "breast cancer", "Phase 2")
        self.assertEqual(result1["markdown"], result2["markdown"])

    # ------------------------------------------------------------------
    # 6. Citation round-trip consistency
    # ------------------------------------------------------------------

    def test_citation_round_trip_consistency(self):
        """Every [N] in body has a References entry; every References entry has a [N] in body."""
        import re
        analysis = _make_analysis(
            primary_endpoints=[
                {"text": "Overall Survival", "frequency": 3, "nct_ids": ["NCT00000001", "NCT00000002"]},
            ],
            secondary_endpoints=[
                {"text": "PFS", "frequency": 2, "nct_ids": ["NCT00000003"]},
            ],
            inclusion_criteria=[
                {"pattern": "Age >= 18", "frequency": 2, "nct_ids": ["NCT00000001"]},
            ],
        )
        result = generate_protocol_outline(analysis, "type 2 diabetes", "Phase 3")
        md = result["markdown"]

        # Split at References section
        ref_match = re.search(r"^## References", md, re.MULTILINE)
        self.assertIsNotNone(ref_match, "References section must exist")

        body_text = md[: ref_match.start()]
        ref_text = md[ref_match.start():]

        # All [N] in body
        body_citations = set(int(m) for m in re.findall(r"\[(\d+)\]", body_text))
        # All [N] defined in References (lines starting with [N])
        ref_citations = set(int(m) for m in re.findall(r"^\[(\d+)\]", ref_text, re.MULTILINE))

        # Every body citation must have a References entry
        for num in body_citations:
            self.assertIn(num, ref_citations, f"[{num}] in body has no References entry")

        # Every References entry must be cited in body
        for num in ref_citations:
            self.assertIn(num, body_citations, f"References entry [{num}] has no body citation")

    # ------------------------------------------------------------------
    # 7. Citation count matches unique NCT IDs
    # ------------------------------------------------------------------

    def test_citation_count_matches_unique_nct_ids(self):
        """citation_count equals number of unique NCT IDs actually cited in the analysis."""
        analysis = _make_analysis(
            primary_endpoints=[
                {"text": "Overall Survival", "frequency": 3, "nct_ids": ["NCT00000001", "NCT00000002"]},
            ],
            secondary_endpoints=[
                {"text": "PFS", "frequency": 2, "nct_ids": ["NCT00000002", "NCT00000003"]},
            ],
            inclusion_criteria=[
                {"pattern": "Age >= 18", "frequency": 2, "nct_ids": ["NCT00000001"]},
            ],
        )
        result = generate_protocol_outline(analysis, "type 2 diabetes", "Phase 3")
        # Unique NCT IDs across all sections: NCT00000001, NCT00000002, NCT00000003
        self.assertEqual(result["citation_count"], 3)


if __name__ == "__main__":
    unittest.main()
