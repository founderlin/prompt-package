"""Backend unit tests.

Uses stdlib ``unittest`` to stay dependency-free — the project doesn't
ship pytest, and Phase 1 of the Wrap feature isn't a good place to
introduce it. If we add pytest later, these tests run unchanged: pytest
auto-discovers ``unittest.TestCase`` subclasses.

Run from ``backend/``::

    python -m unittest discover -s tests -v
"""
