from app.cache import SnapshotCache


async def test_cache_keeps_last_good_values_on_failure():
    cache = SnapshotCache()

    await cache.update_success("immich", {"imm_photos": 12})
    await cache.update_failure("immich", "timeout")
    payload = await cache.payload()

    assert payload["imm_photos"] == 12
    assert payload["imm_ok"] is False
    assert payload["imm_err"] == "timeout"
    assert isinstance(payload["imm_age"], int)


async def test_empty_cache_has_no_success():
    cache = SnapshotCache()

    assert await cache.has_any_success() is False

