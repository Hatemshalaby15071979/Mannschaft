"""V6 media: one recommended clip per lesson, chosen from the existing corpus.

Nothing here invents a video. The selector only ranks clips that already exist
in ``content/corpus/clips.jsonl`` and records why it chose one. When nothing
clears the threshold the honest answer is ``primary: null`` plus the rendered
audio fallback.
"""

from .manifest import LessonMedia, MediaManifest, MediaPick, Relevance

__all__ = ["LessonMedia", "MediaManifest", "MediaPick", "Relevance"]
