from collections.abc import Sequence

from leisurelog.domain.models import ActivityEvent, Classification
from leisurelog.domain.ports import Classifier


class ClassificationPipeline:
    def __init__(self, classifiers: Sequence[Classifier], timing_rules=(), context_classifiers=()):
        self.classifiers = classifiers
        self.timing_rules = timing_rules
        self.context_classifiers = context_classifiers

    def for_processing(self):
        """Prepare host-owned batch views once, without giving plugins a repository."""
        return ClassificationPipeline(
            [
                classifier.for_processing()
                if callable(getattr(classifier, "for_processing", None))
                else classifier
                for classifier in self.classifiers
            ],
            self.timing_rules,
            self.context_classifiers,
        )

    def classify(self, event: ActivityEvent, manual: Classification | None) -> Classification:
        if manual is not None:
            return manual
        for classifier in self.classifiers:
            result = classifier.classify(event)
            if result is not None:
                return result
        return Classification()
