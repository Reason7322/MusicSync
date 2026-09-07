"""Run all offline tests and save per-test/subtest release evidence.

Real rsync/ReplayGain operations in this suite use only temporary test libraries.
There is no real-phone mode in this script.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + os.environ.get('PYTHONPATH', '')


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        self.started_at = time.monotonic()
        super().startTest(test)

    def record(self, test, status, detail=''):
        self.records.append({'test': test.id(), 'status': status, 'seconds': round(time.monotonic() - self.started_at, 4), 'detail': detail})

    def addSuccess(self, test):
        self.record(test, 'PASS')
        super().addSuccess(test)

    def addFailure(self, test, error):
        self.record(test, 'FAIL', self._exc_info_to_string(error, test))
        super().addFailure(test, error)

    def addError(self, test, error):
        self.record(test, 'FAIL', self._exc_info_to_string(error, test))
        super().addError(test, error)

    def addSkip(self, test, reason):
        self.record(test, 'NOT TESTED', reason)
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, error):
        self.record(subtest, 'FAIL' if error else 'PASS', self._exc_info_to_string(error, test) if error else '')
        super().addSubTest(test, subtest, error)


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    evidence = {'at': datetime.now().astimezone().isoformat(timespec='seconds'), 'tests_run': result.testsRun,
                'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
                'seconds': round(time.monotonic() - started, 3), 'tests': result.records}
    path = ROOT / 'docs/release-test-results.json'
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=True) + '\n')
    print(f'Release evidence: {path}')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
