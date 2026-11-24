import io
from unittest.mock import MagicMock

import av
import numpy as np

from media import film


def _clip(color: int, frames: int = 6, size=(64, 48)) -> bytes:
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as c:
        s = c.add_stream("libx264", rate=24)
        s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"
        for i in range(frames):
            img = np.full((size[1], size[0], 3), color if i < frames - 1 else 255 - color, dtype=np.uint8)
            for p in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return out.getvalue()


def _frames(video: bytes) -> int:
    with av.open(io.BytesIO(video)) as c:
        return sum(1 for _ in c.decode(video=0))


def test_scenes_are_planned_and_bad_answers_fall_back():
    ollama = MagicMock()
    ollama.chat.return_value = ('{"escenas": [{"prompt": "An astronaut walks on Mars.", "segundos": 5}, '
                                '{"prompt": "He finds a dog.", "segundos": 30}, {"prompt": ""}]}')
    assert film.plan_scenes(ollama, "m", "una peli de un astronauta") == [
        {"prompt": "An astronaut walks on Mars.", "segundos": 5.0}, {"prompt": "He finds a dog.", "segundos": 8.0}]
    ollama.chat.return_value = "no se"
    assert film.plan_scenes(ollama, "m", "una peli") == [{"prompt": "una peli", "segundos": 4.0}]


def test_each_scene_starts_from_the_last_frame_of_the_previous_and_all_are_joined():
    red, blue = _clip(200), _clip(30)
    calls = []

    def t2v(prompt, seconds):
        calls.append(("texto", prompt))
        return red

    def i2v(prompt, frame, seconds):
        calls.append(("imagen", prompt, frame[:8]))
        return blue

    movie, clips = film.make([{"prompt": "a", "segundos": 4}, {"prompt": "b", "segundos": 4},
                              {"prompt": "c", "segundos": 4}], t2v, i2v)
    assert [c[0] for c in calls] == ["texto", "imagen", "imagen"]
    assert all(c[2] == b"\x89PNG\r\n\x1a\n" for c in calls[1:])
    assert len(clips) == 3 and _frames(movie) == 6


def test_scenes_crossfade_instead_of_jumping():
    dark, light = _clip(0, frames=30), _clip(250, frames=30)
    movie = film.concat([dark, light], fade=12)
    with av.open(io.BytesIO(movie)) as c:
        means = [f.to_ndarray(format="rgb24").mean() for f in c.decode(video=0)]
    assert len(means) == 48
    middle = means[18:30]
    assert all(b >= a - 2 for a, b in zip(middle, middle[1:])) and middle[0] < 100 < middle[-1]
    assert _frames(film.concat([dark, light], fade=0)) == 60


def test_redo_changes_only_one_scene_starting_where_the_previous_ends():
    first, second, third = _clip(200), _clip(30), _clip(120)
    used = []
    movie, clips = film.redo([{"prompt": "a", "segundos": 4}, {"prompt": "b", "segundos": 4}], [first, second], 1,
                             lambda p, s: b"", lambda p, f, s: used.append((p, f)) or third)
    assert clips == [first, third] and used == [("b", film.last_frame(first))]
    assert _frames(movie) > 0


def test_transform_changes_every_frame_and_keeps_the_length():
    clip = _clip(200)
    seen = []
    out = film.transform(clip, lambda img: seen.append(img.shape) or (img // 2))
    assert _frames(out) == _frames(clip) == len(seen)
    with av.open(io.BytesIO(out)) as c:
        first = next(c.decode(video=0)).to_ndarray(format="rgb24")
    assert first.mean() < 150
