"""
Dataset utilities for 02_train_classifier. Must be a separate module so
FilteredImageFolder can be pickled when DataLoader uses num_workers > 0.
"""

from torchvision import datasets


EXCLUDE_CLASSES = {"cortaderia_selloana_(schult._&_schult.f.)_asch._&_graebn."}


class FilteredImageFolder(datasets.ImageFolder):
    """ImageFolder that excludes certain class folders (e.g. duplicate cortaderia)."""

    def find_classes(self, directory):
        classes, class_to_idx = super().find_classes(directory)
        classes = [c for c in classes if c not in EXCLUDE_CLASSES]
        class_to_idx = {cls_name: i for i, cls_name in enumerate(classes)}
        return classes, class_to_idx
