import pytest
from hypothesis import given, settings, strategies as st

from archive_security import ArchiveLimits, ArchivePolicyError, safe_member_path


LIMITS = ArchiveLimits(
    max_extracted_bytes=1024**3,
    max_members=1000,
    max_member_bytes=1024**2,
    max_path_depth=16,
    max_name_bytes=512,
    max_compression_ratio=1000,
    scratch_reserve_bytes=0,
)


SAFE_PART = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters="/\\:\x00",
    ),
    min_size=1,
    max_size=20,
).filter(lambda value: value not in {".", ".."})


@given(st.lists(SAFE_PART, min_size=1, max_size=12))
@settings(max_examples=150)
def test_safe_members_remain_relative(parts):
    member = "/".join(parts)
    safe = safe_member_path(member, LIMITS)
    assert not safe.is_absolute()
    assert ".." not in safe.parts


@given(
    prefix=st.sampled_from(["../", "../../", "/", "C:\\", "dir/../../../"]),
    suffix=SAFE_PART,
)
def test_unsafe_member_prefixes_are_rejected(prefix, suffix):
    with pytest.raises(ArchivePolicyError):
        safe_member_path(prefix + suffix, LIMITS)


def test_member_name_and_depth_limits_are_enforced():
    with pytest.raises(ArchivePolicyError):
        safe_member_path("/".join(["x"] * 17), LIMITS)
    with pytest.raises(ArchivePolicyError):
        safe_member_path("x" * 513, LIMITS)


def test_windows_separators_cannot_hide_parent_traversal():
    with pytest.raises(ArchivePolicyError):
        safe_member_path(r"safe\..\escape", LIMITS)
