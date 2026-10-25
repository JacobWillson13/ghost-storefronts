import httpx

from storefronts import download as dl


def _mock_api(total_rows: int, fail_first: bool = False):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if fail_first and calls["n"] == 1:
            return httpx.Response(503)
        limit = int(request.url.params["$limit"])
        offset = int(request.url.params["$offset"])
        assert request.url.params["$order"] == ":id"
        rows = [{"rec_id": str(i)} for i in range(offset, min(offset + limit, total_rows))]
        return httpx.Response(200, json=rows)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_paged_download_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)
    client, _ = _mock_api(25, fail_first=True)
    # Stop after 2 pages to simulate an interrupted run, then resume.
    m = dl.download_source(
        "archive",
        since="2010-01-01",
        page_size=10,
        max_pages=2,
        data_dir=tmp_path,
        run_id="r1",
        http=client,
        log=lambda *_: None,
    )
    assert m["complete"] is False
    assert m["pages"] == {"0": 10, "1": 10}
    m = dl.download_source(
        "archive",
        since="2010-01-01",
        page_size=10,
        data_dir=tmp_path,
        run_id="r1",
        http=client,
        log=lambda *_: None,
    )
    assert m["complete"] is True
    assert m["rows"] == 25
    rows = [r for _, r in dl.iter_rows(tmp_path / "raw" / "archive" / "r1")]
    assert [r["rec_id"] for r in rows] == [str(i) for i in range(25)]
    assert dl.latest_run_dir("archive", tmp_path).name == "r1"


def test_where_clause_uses_date_field(tmp_path):
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    dl.download_source(
        "archive",
        since="2010-01-01",
        page_size=5,
        data_dir=tmp_path,
        run_id="r2",
        http=client,
        log=lambda *_: None,
    )
    assert seen["$where"] == "insp_dt >= '2010-01-01T00:00:00'"
