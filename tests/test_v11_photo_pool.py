"""Property-based tests for the v1.1.0 photo-pool core seams.

Covers three design correctness properties for the Photo_Pool helpers in
``outreach_drafts.py`` (Tasks 2.3, 2.4, 2.5):

- Property 7: Photo-pool seeding is idempotent (Req 3.2).
- Property 8: Add then remove restores the photo pool (Req 3.4, 3.5).
- Property 5: Random selection returns exactly two distinct pool photos (Req 3.6).

Design reference: .kiro/specs/outreach-app-v1-1/design.md.

These tests exercise the pure directory-argument seams (``seed_photo_pool``,
``list_pool_photos``, ``add_pool_photos``, ``remove_pool_photo``,
``select_pool_photos``) with no GUI and no display. Tiny-but-valid image files
are produced by copying the real bytes of a bundled project attachment, so the
image-extension filtering in the pool helpers behaves exactly as in production.

Because Hypothesis re-runs the test body many times against a single
function-scoped fixture, the ``tmp_path`` fixture is NOT used inside ``@given``
tests: each example builds its own temporary directories with ``tempfile`` and
cleans them up, so examples never share state.
"""
import os
import random
import shutil
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

import outreach_drafts

# A real, valid image from the project. We copy its bytes into temp files with
# varied names so the pool helpers see genuine image content (not empty stubs),
# matching the extension filtering used in production.
_SEED_IMAGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "attachments",
    "robot-demo4.jpg",
)


def _make_image(directory, name):
    """Create a valid image file named ``name`` in ``directory`` by copying the
    bytes of the real project attachment. Returns the created file path."""
    dest = os.path.join(directory, name)
    shutil.copyfile(_SEED_IMAGE, dest)
    return dest


def _pool_basenames(pool_dir):
    """Return the set of image file basenames currently in ``pool_dir``."""
    return {os.path.basename(p) for p in outreach_drafts.list_pool_photos(pool_dir)}


# ---------------------------------------------------------------------------
# Task 2.3 — Property 7: Photo-pool seeding is idempotent (Req 3.2)
# ---------------------------------------------------------------------------
@settings(max_examples=100)
@given(n=st.integers(min_value=1, max_value=6))
def test_seeding_is_idempotent(n):
    """Feature: outreach-app-v1-1, Property 7: Photo-pool seeding is idempotent.

    Seeding an empty pool from a seed dir holding N images makes the pool
    contain exactly those N images; seeding a second time leaves the pool
    contents unchanged (seed twice == seed once).

    Validates: Requirements 3.2.
    """
    base = tempfile.mkdtemp()
    try:
        seed_dir = os.path.join(base, "seed")
        pool_dir = os.path.join(base, "pool")
        os.makedirs(seed_dir)

        # Build a seed dir with N distinct valid images.
        expected = set()
        for i in range(n):
            name = f"seed_{i}.jpg"
            _make_image(seed_dir, name)
            expected.add(name)

        # Pool starts empty.
        assert outreach_drafts.list_pool_photos(pool_dir) == []

        # First seed: the empty pool is filled with the N seed images.
        outreach_drafts.seed_photo_pool(pool_dir, seed_dir)
        after_first = _pool_basenames(pool_dir)
        assert after_first == expected
        assert len(after_first) == n

        # Second seed: no-op because the pool is already non-empty.
        outreach_drafts.seed_photo_pool(pool_dir, seed_dir)
        after_second = _pool_basenames(pool_dir)
        assert after_second == after_first
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Task 2.4 — Property 8: Add then remove restores the pool (Req 3.4, 3.5)
# ---------------------------------------------------------------------------
@settings(max_examples=100)
@given(
    initial=st.integers(min_value=0, max_value=5),
    added_name=st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
        ),
        min_size=1,
        max_size=12,
    ),
)
def test_add_then_remove_restores_pool(initial, added_name):
    """Feature: outreach-app-v1-1, Property 8: Add then remove restores the pool.

    Starting from an arbitrary pool, adding an image then removing that same
    filename returns the pool to its prior set of files, and the removed file is
    absent afterward.

    Validates: Requirements 3.4, 3.5.
    """
    base = tempfile.mkdtemp()
    try:
        pool_dir = os.path.join(base, "pool")
        src_dir = os.path.join(base, "src")
        os.makedirs(pool_dir)
        os.makedirs(src_dir)

        # Seed the starting pool with `initial` distinct images.
        for i in range(initial):
            _make_image(pool_dir, f"pool_{i}.jpg")
        prior = _pool_basenames(pool_dir)

        # Build a source image whose basename does not collide with the pool.
        add_filename = f"{added_name}_add.jpg"
        while add_filename in prior:
            add_filename = "x" + add_filename
        source = _make_image(src_dir, add_filename)

        # Add the image; it becomes a pool member.
        outreach_drafts.add_pool_photos(pool_dir, [source])
        assert add_filename in _pool_basenames(pool_dir)

        # Remove that same filename; the pool returns to its prior set.
        outreach_drafts.remove_pool_photo(pool_dir, add_filename)
        after = _pool_basenames(pool_dir)
        assert after == prior
        assert add_filename not in after
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Task 2.5 — Property 5: Random 2-of-pool selection (Req 3.6)
# ---------------------------------------------------------------------------
@settings(max_examples=100)
@given(n=st.integers(min_value=2, max_value=8))
def test_select_two_distinct_pool_photos(n):
    """Feature: outreach-app-v1-1, Property 5: Random selection returns exactly
    two distinct pool photos.

    For a pool holding at least two images, ``select_pool_photos(pool, 2)``
    returns exactly two distinct paths, each of which is a member of the pool.

    Validates: Requirements 3.6.
    """
    base = tempfile.mkdtemp()
    try:
        pool_dir = os.path.join(base, "pool")
        os.makedirs(pool_dir)

        for i in range(n):
            _make_image(pool_dir, f"pool_{i}.jpg")
        pool = set(outreach_drafts.list_pool_photos(pool_dir))
        assert len(pool) == n

        selected = outreach_drafts.select_pool_photos(pool_dir, 2, rng=random)

        # Exactly two results.
        assert len(selected) == 2
        # Distinct.
        assert len(set(selected)) == 2
        # Each is a pool member.
        for path in selected:
            assert path in pool
    finally:
        shutil.rmtree(base, ignore_errors=True)
