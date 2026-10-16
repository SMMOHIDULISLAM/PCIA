import unittest
from pathlib import Path

from pcia.extract import EvidenceExtractor
from pcia.models import DocumentPage


class PubaliTableTests(unittest.TestCase):
    def test_facility_and_financial_tables(self):
        root = Path(__file__).resolve().parents[1]
        extractor = EvidenceExtractor(root / "config" / "field_rules.json", root / "config" / "source_priority.json")
        page = DocumentPage(
            relative_path="FL-59.pdf",
            page_number=1,
            text="CREDIT APPLICATION FORM\nFigure in Lac Taka",
            document_type="loan_application",
            extraction_method="test",
            readable=True,
            metadata={
                "entity_role": "case",
                "tables": [
                    [
                        ["Type of Facility", "Purpose of Facility", "Limit/Amount", "Pricing"],
                        ["Pubali Krishi Uddokta Rin", "For Agri Credit", "5,00,000.00", "13%"],
                    ],
                    [
                        ["Particulars", "Last Year 2024", "Current Year 2025"],
                        ["Total Sale", "25.00", "30.00"],
                        ["Net Profit/Earning After Tax", "10.50", "14.56"],
                    ],
                ],
            },
        )
        candidates = [x for x in extractor.extract([page]) if x.valid]
        values = {(x.field_name, x.normalized_value) for x in candidates}
        self.assertIn(("loan_product", "pubali krishi uddokta rin"), values)
        self.assertIn(("loan_amount", "500000.00"), values)
        self.assertIn(("sales", "3000000.00"), values)
        self.assertIn(("net_profit", "1456000.00"), values)


if __name__ == "__main__":
    unittest.main()
