from fpl_agent.ingestion.eo_sample import select_stratified_pages


def test_select_stratified_pages_spans_full_rank_range():
    pages = select_stratified_pages(target_sample_size=750)

    assert pages[0] == 1
    assert pages[-1] == 200  # 10000 ranks / 50 per page
    assert pages == sorted(set(pages))  # strictly increasing, no duplicates
    assert 10 <= len(pages) <= 15  # ceil(750/50) == 15, rounding may merge a couple


def test_select_stratified_pages_small_target_returns_first_page_only():
    assert select_stratified_pages(target_sample_size=10) == [1]


def test_select_stratified_pages_never_exceeds_max_page():
    pages = select_stratified_pages(target_sample_size=100000)  # way over budget

    assert pages[-1] == 200
    assert len(pages) == 200
