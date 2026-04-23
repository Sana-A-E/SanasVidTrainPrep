"""
spellcheck_highlighter.py
=========================
A ``QSyntaxHighlighter`` subclass that underlines misspelled English words
inside a ``QTextEdit`` using the ``pyspellchecker`` library.

Features:
- Language: English US (``en``).
- Skips pure numbers, contractions (``don't``, ``it's``), and very short
  tokens (length ≤ 1) to reduce false positives.
- Uses a dashed red underline (``SpellCheckUnderline``) — visually distinct
  from the normal syntax-highlighter squiggles so it feels native.
- Gracefully degrades: if ``pyspellchecker`` is not installed the highlighter
  is a no-op and a single warning is printed instead of crashing the app.
"""

import re
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt6.QtCore import Qt

# ── Attempt to import the spell-check backend ─────────────────────────────────
try:
    from spellchecker import SpellChecker  # pyspellchecker >= 0.7
    _SPELLCHECKER_AVAILABLE = True
except ImportError:
    _SPELLCHECKER_AVAILABLE = False
    print(
        "⚠️ pyspellchecker is not installed.  Spellchecking will be disabled.\n"
        "   Install it with:  pip install pyspellchecker==0.8.1"
    )

# Pre-compiled pattern: tokenise words (including apostrophes for contractions)
# We match sequences of letters and apostrophes, ensuring we don't start/end with an apostrophe.
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*|[A-Za-z]")


class SpellCheckHighlighter(QSyntaxHighlighter):
    """
    Syntax highlighter that underlines misspelled English words in red.

    Attach it to a ``QTextEdit`` by passing the document as the parent::

        highlighter = SpellCheckHighlighter(text_edit.document())

    The highlighter is a no-op when ``pyspellchecker`` is not installed.
    """

    def __init__(self, parent=None):
        """
        Initialise the highlighter and the spell-checker backend.

        Args:
            parent: A ``QTextDocument`` (or any valid ``QObject`` parent).
                Typically ``text_edit.document()``.
        """
        super().__init__(parent)

        # Build the underline format once; reuse it for every misspelled word
        self._error_format = QTextCharFormat()
        self._error_format.setUnderlineStyle(
            QTextCharFormat.UnderlineStyle.SpellCheckUnderline
        )
        self._error_format.setUnderlineColor(QColor("#FF4444"))  # Vivid red

        # Initialise the spell-checker (English US dictionary)
        if _SPELLCHECKER_AVAILABLE:
            self._spell = SpellChecker(language="en")
        else:
            self._spell = None

    # ── QSyntaxHighlighter interface ──────────────────────────────────────────

    def highlightBlock(self, text: str) -> None:
        """
        Called by Qt for every block (paragraph) that needs re-highlighting.

        Tokenises ``text`` into words and underlines any that the spell-checker
        does not recognise.

        Args:
            text (str): The raw text of the current block.
        """
        if self._spell is None:
            return  # Spell-checker not available — nothing to do

        for match in _WORD_RE.finditer(text):
            word = match.group()
            lower_word = word.lower()

            # Special handling for single-letter words. 
            # In English, only 'a' and 'i' are valid as standalone words.
            if len(lower_word) == 1:
                if lower_word not in ('a', 'i'):
                    self.setFormat(match.start(), len(word), self._error_format)
                continue

            # For multi-letter words, check the dictionary.
            if lower_word in self._spell:
                continue  # Correctly spelled

            # Apply the red underline to the exact character range
            self.setFormat(match.start(), len(word), self._error_format)

    # ── Public helpers ────────────────────────────────────────────────────────

    def get_suggestions(self, word: str):
        """Returns a list of spelling suggestions for the given word."""
        if self._spell:
            # Strip apostrophes for checking but keep context
            clean_word = word.strip("'")
            return list(self._spell.candidates(clean_word.lower()))[:5]
        return []

    def is_misspelled(self, word: str) -> bool:
        """Checks if a word is misspelled."""
        if self._spell:
            clean_word = word.strip("'")
            if not clean_word: return False
            return clean_word.lower() not in self._spell
        return False

    def add_word(self, word: str) -> None:
        """
        Add a word to the spell-checker's in-session known-word list.

        This is useful for domain-specific terms (character names, trigger
        words, etc.) so they are not flagged as errors.

        Args:
            word (str): The word to whitelist.
        """
        if self._spell is not None:
            self._spell.word_frequency.add(word.lower())
            self.rehighlight()
