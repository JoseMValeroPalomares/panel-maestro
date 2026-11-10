"""Los vídeos de YouTube se identifican por su ID: sin duplicados con parámetros, listas, shorts o youtu.be."""
import pytest

from app.scraper import youtube_video_id

ID = "zXyWvUtSrQp"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={ID}",
    f"https://www.youtube.com/watch?v={ID}&list=PLabc&index=3&t=42s",
    f"https://www.youtube.com/watch?list=PLabc&v={ID}",
    f"https://youtu.be/{ID}", f"https://youtu.be/{ID}?si=xyz&t=10",
    f"https://www.youtube.com/shorts/{ID}", f"https://m.youtube.com/watch?v={ID}", f"https://music.youtube.com/watch?v={ID}",
    f"https://www.youtube.com/live/{ID}?feature=share", f"https://www.youtube.com/embed/{ID}",
])
def test_mismo_id_con_cualquier_url(url):
    assert youtube_video_id(url) == ID


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/@usuario", "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv", "https://www.youtube.com/c/algo",
    "https://www.youtube.com/playlist?list=PLabc", "https://www.youtube.com/", f"https://otra.web/watch?v={ID}", "no es una url",
])
def test_no_es_un_video(url):
    assert youtube_video_id(url) is None


def test_baul_no_duplica_y_marca_como_visto(client):
    base = {"category": "YT Test"}
    assert client.post("/api/resources", json={"url": f"https://www.youtube.com/watch?v={ID}&list=PLx", **base}).status_code == 200
    assert client.post("/api/resources", json={"url": f"https://youtu.be/{ID}?t=5", **base}).status_code == 409          # mismo vídeo
    r = client.post("/api/resources", json={"url": f"https://www.youtube.com/shorts/{ID}", "watched": True, **base})
    assert r.status_code == 200 and r.json()["status"] == "updated"                                                      # lo marca como visto
    rows = [x for x in client.get("/api/resources").json()["resources"] if ID in x["url"]]
    assert len(rows) == 1 and rows[0]["watched"] == 1 and rows[0]["url"] == f"https://www.youtube.com/watch?v={ID}"


def test_endpoint_estado_del_video(client):
    vid = "qrstuvwxyz1"
    assert client.get("/api/ext/youtube/video", params={"id": vid}).json()["exists"] is False
    client.post("/api/resources", json={"url": f"https://youtu.be/{vid}", "category": "YT Test", "watch_later": True})
    r = client.get("/api/ext/youtube/video", params={"id": vid}).json()
    assert r["exists"] and r["watch_later"] and not r["watched"]
    assert client.get("/api/ext/youtube/video", params={"id": "mal"}).status_code == 400
