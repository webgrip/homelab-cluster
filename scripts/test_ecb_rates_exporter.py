import importlib.util
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPORTER = Path(os.environ.get(
    "EXPORTER_SCRIPT",
    REPO_ROOT / "kubernetes/apps/observability/ecb-rates-exporter/app/ecb_rates_exporter.py"))

spec = importlib.util.spec_from_file_location("ecb_rates_exporter", EXPORTER)
exporter = importlib.util.module_from_spec(spec)
sys.modules["ecb_rates_exporter"] = exporter
spec.loader.exec_module(exporter)

ECB_DOCUMENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time='2026-10-23'>
      <Cube currency='USD' rate='1.1193'/>
      <Cube currency='GBP' rate='0.83728'/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


class ParseTest(unittest.TestCase):
    def test_reads_every_currency_of_the_dated_cube(self):
        rates, _ = exporter.parse(ECB_DOCUMENT)
        self.assertEqual(rates, {"USD": 1.1193, "GBP": 0.83728})

    def test_reads_the_publication_day_as_utc_midnight(self):
        _, day = exporter.parse(ECB_DOCUMENT)
        self.assertEqual(day, 1792713600.0)

    def test_document_without_rates_is_an_error(self):
        with self.assertRaises(ValueError):
            exporter.parse(b"<Envelope xmlns='http://www.ecb.int/vocabulary/2002-08-01/eurofxref'><Cube><Cube time='2026-10-23'/></Cube></Envelope>")


class ExporterTest(unittest.TestCase):
    def test_metrics_carry_units_per_euro(self):
        instance = exporter.Exporter(lambda: ECB_DOCUMENT)
        instance.refresh()
        self.assertIn('ecb_reference_rate{currency="USD"} 1.1193', instance.metrics())

    def test_failed_fetch_keeps_the_last_good_rates_and_counts_a_failure(self):
        documents = iter([ECB_DOCUMENT, b"not xml"])
        instance = exporter.Exporter(lambda: next(documents))
        instance.refresh()
        first_success = instance.snapshot.last_success
        instance.refresh()
        self.assertEqual(instance.snapshot.rates["USD"], 1.1193)
        self.assertEqual(instance.snapshot.refresh_failures, 1)
        self.assertEqual(instance.snapshot.last_success, first_success)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *sys.argv[1:]], verbosity=1)
