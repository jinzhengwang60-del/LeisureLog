from collections.abc import Sequence

from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.domain.ports import Classifier


class ClassificationPipeline:
    def __init__(self, classifiers: Sequence[Classifier], timing_rules=()):
        self.classifiers = classifiers
        self.timing_rules = timing_rules

    def classify(self, event: ActivityEvent, manual: Classification | None) -> Classification:
        if manual is not None:
            return manual
        for classifier in self.classifiers:
            result = classifier.classify(event)
            if result is not None:
                return result
        return Classification()
