import unittest
from pathlib import Path

from pcia.extract import EvidenceExtractor
from pcia.models import DocumentPage, EvidenceCandidate
from pcia.resolve import EvidenceResolver
from pcia.semantics import classify_entity_name
from pcia.validate import validate_candidate
from pcia.variations import build_variation_explanations


class VariationRuleTests(unittest.TestCase):
    def _candidate(self, field, value, normalized, priority=90, confidence=0.95, path="a.pdf"):
        return EvidenceCandidate(
            field_name=field, value=value, normalized_value=normalized,
            relative_path=path, page_number=1, document_type="loan_application",
            confidence=confidence, source_priority=priority, pattern_id="test", raw_match=value,
            valid=True, rejection_reason="",
        )

    def test_account_formats_compare_by_digits_but_preserve_display(self):
        valid1, _, value1, norm1 = validate_candidate("account_number", "CD-123456")
        valid2, _, value2, norm2 = validate_candidate("account_number", "CD/123456")
        self.assertTrue(valid1 and valid2)
        self.assertEqual(norm1, norm2)
        self.assertEqual(value1, "CD-123456")
        result = EvidenceResolver().resolve([
            self._candidate("account_number", value1, norm1, path="a.pdf"),
            self._candidate("account_number", value2, norm2, path="b.pdf"),
        ])
        self.assertEqual(result["account_number"].status, "resolved")
        self.assertFalse(result["account_number"].conflict)
        self.assertIn("CD", result["account_number"].selected_value)


    def test_segmented_full_account_equals_direct_13_digit(self):
        valid1, _, value1, norm1 = validate_candidate("account_number", "3043901007337")
        valid2, _, value2, norm2 = validate_candidate("account_number", "3043-901-7337")
        self.assertTrue(valid1 and valid2)
        self.assertEqual(norm1, norm2)
        result = EvidenceResolver().resolve([
            self._candidate("account_number", value1, norm1, path="a.pdf"),
            self._candidate("account_number", value2, norm2, path="b.pdf"),
        ])
        self.assertFalse(result["account_number"].conflict)

    def test_firm_and_individual_are_separate(self):
        self.assertEqual(classify_entity_name("M/s Bandhan Agro & Poultry Farm"), "firm")
        self.assertEqual(classify_entity_name("Md. Afu Mia"), "individual")
        valid, reason, *_ = validate_candidate("business_name", "Md. Afu Mia")
        self.assertFalse(valid)
        self.assertIn("individual", reason)

    def test_mia_miah_is_not_a_conflict(self):
        result = EvidenceResolver().resolve([
            self._candidate("proprietor_name", "Md. Afu Mia", "md afu mia", path="a.pdf"),
            self._candidate("proprietor_name", "Md. Afu Miah", "md afu miah", path="b.pdf"),
        ])
        self.assertEqual(result["proprietor_name"].status, "resolved")
        self.assertFalse(result["proprietor_name"].conflict)

    def test_both_nid_formats_are_retained(self):
        result = EvidenceResolver().resolve([
            self._candidate("nid", "1234567890", "1234567890", path="nid-smart.pdf"),
            self._candidate("nid", "19801234567890123", "19801234567890123", path="nid-old.pdf"),
        ])
        self.assertEqual(result["nid"].status, "resolved")
        self.assertIn("1234567890", result["nid"].selected_value)
        self.assertIn("19801234567890123", result["nid"].selected_value)
        self.assertFalse(result["nid"].conflict)

    def test_rate_roles_do_not_conflict(self):
        result = EvidenceResolver().resolve([
            self._candidate("general_interest_rate", 13.0, "13.0000", path="product.pdf"),
            self._candidate("branch_recommended_rate", 12.0, "12.0000", priority=100, path="forwarding.pdf"),
        ])
        self.assertEqual(result["interest_rate"].selected_value, 12.0)
        self.assertEqual(result["interest_rate"].selected_source["rate_role"], "branch-recommended rate")
        self.assertFalse(result["interest_rate"].conflict)
        explanations = build_variation_explanations([], result)
        self.assertTrue(any(x["category"] == "interest_rate_context" for x in explanations))


if __name__ == "__main__":
    unittest.main()
