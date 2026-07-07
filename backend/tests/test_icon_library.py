from app import icon_library


def test_slug_for_domain_replaces_dots_and_slashes():
    assert icon_library.slug_for_domain("netflix.com") == "netflix_com"
    assert icon_library.slug_for_domain("music.youtube.com") == "music_youtube_com"
    assert icon_library.slug_for_domain("a.b/c") == "a_b_c"


def test_services_have_unique_slugs():
    """内置服务的 slug 必须唯一，否则 seed 幂等导入会漏掉同 slug 条目。"""
    slugs = [icon_library.slug_for_domain(domain) for _, domain, _ in icon_library.SERVICES]
    assert len(slugs) == len(set(slugs))


def test_carrier_services_include_added_regional_carriers():
    """新增的区域电信运营商必须在内置 carrier 列表里。"""
    carriers = {name for name, _, cat in icon_library.SERVICES if cat == "carrier"}
    for name in ["Skinny", "MTN Nigeria", "Club Sim", "CTM 澳门电信", "Simyo", "Yallo"]:
        assert name in carriers, f"缺少内置运营商：{name}"


def test_valid_category_keys_contains_other():
    keys = icon_library.valid_category_keys()
    assert "other" in keys
    # 几个常见主分类应存在
    for k in ("streaming", "vps", "ai"):
        assert k in keys


def test_categories_items_have_key_and_label():
    items = icon_library.categories()
    assert items, "categories 不应为空"
    for item in items:
        assert "key" in item
        assert "label" in item


def test_normalize_category_keys_none_without_fallback_returns_other():
    assert icon_library.normalize_category_keys(None) == ["other"]


def test_normalize_category_keys_single_valid_string():
    assert icon_library.normalize_category_keys("streaming") == ["streaming"]


def test_normalize_category_keys_list_dedup_and_keep_order():
    # 去重、保留顺序、过滤空值
    assert icon_library.normalize_category_keys(["streaming", "streaming", "", "music"]) == ["streaming", "music"]


def test_normalize_category_keys_json_string_list():
    assert icon_library.normalize_category_keys('["streaming", "music"]') == ["streaming", "music"]


def test_normalize_category_keys_non_json_string_treated_as_single():
    assert icon_library.normalize_category_keys("streaming") == ["streaming"]


def test_normalize_category_keys_drops_unknown_by_default():
    # 未知 key 默认被丢弃，最终回 other
    assert icon_library.normalize_category_keys(["streaming", "nope"]) == ["streaming"]
    assert icon_library.normalize_category_keys(["totally-unknown"]) == ["other"]


def test_normalize_category_keys_allow_unknown_keeps_them():
    assert icon_library.normalize_category_keys(["streaming", "custom-x"], allow_unknown=True) == ["streaming", "custom-x"]


def test_normalize_category_keys_fallback_used_when_main_empty():
    # 主输入全无效时，fallback 生效
    assert icon_library.normalize_category_keys(None, fallback="vps") == ["vps"]
    assert icon_library.normalize_category_keys(["totally-unknown"], fallback="vps") == ["vps"]


def test_normalize_category_keys_all_invalid_returns_other():
    assert icon_library.normalize_category_keys("", fallback=None) == ["other"]
