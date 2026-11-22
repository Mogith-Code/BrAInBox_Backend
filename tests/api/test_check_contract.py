"""scripts/check_contract.py: every frontend api.* call has a backend route."""

import os
from pathlib import Path

import pytest

from scripts.check_contract import (
    ALLOWED_UNMATCHED,
    check,
    load_routes,
    main,
    scan_frontend,
    stale_allow_list,
)

# The frontend repo as cloned on the team PCs (set BRAINBOX_FRONTEND to point elsewhere).
FRONTEND = Path(
    os.environ.get("BRAINBOX_FRONTEND")
    or Path(__file__).resolve().parents[4] / "Brainbox-Mobile" / "BrAInBox_Mobile"
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _found(root: Path) -> set[tuple[str, str]]:
    return {(c.method, c.path) for c in scan_frontend(root)}


def test_scan_finds_literals_base_params_and_multiline_calls(tmp_path):
    _write(
        tmp_path,
        "apps/mobile/lib/features/x/data/repo.dart",
        """
class Repo {
  static const _base = '/learn';
  Future<void> a() => api.get<Map<String, dynamic>>('/auth/me');
  Future<void> b() => api.post<List<Map<String, dynamic>>>(
        '$_base/topics/$topicId/notes/generate',
        data: {'x': 1},
      );
  Future<void> c() => api.get<Object?>('${_base}/units/u$unitNumber?full=true');
  Future<void> d() => api.delete<Object?>('/posts/${post.id}/');
  Future<void> e() => api.upload<Object?>('/evaluations/pages', formData: f);
}
""",
    )
    assert _found(tmp_path) == {
        ("GET", "/auth/me"),
        ("POST", "/learn/topics/{}/notes/generate"),
        ("GET", "/learn/units/{}"),
        ("DELETE", "/posts/{}"),
        ("POST", "/evaluations/pages"),
    }


def test_scan_skips_comments_and_generated_files(tmp_path):
    _write(
        tmp_path,
        "packages/brainbox_core/lib/api/api_client.dart",
        """
/// await api.upload('/evaluations/handwritten', formData: form);
// api.get('/commented/out');
/* api.post('/block/comment'); */
final url = 'http://x//api.get("/in/a/string")';
Future<void> real() => api.get<Object?>('/real');
""",
    )
    _write(tmp_path, "apps/admin/lib/x.g.dart", "f() => api.get('/generated');")
    _write(tmp_path, "apps/admin/lib/x.freezed.dart", "f() => api.get('/frozen');")
    _write(tmp_path, "apps/other/lib/x.dart", "f() => api.get('/not/scanned');")
    assert _found(tmp_path) == {("GET", "/real")}


def test_scan_follows_path_helpers_and_switches(tmp_path):
    _write(
        tmp_path,
        "apps/admin/lib/repo.dart",
        """
class Repo {
  static const _base = '/admin/syllabus';
  Future<Object?> _cached(String path, [Map<String, dynamic>? query]) =>
      cache.getJson(path, () => api.get<Object?>(path, query: query));
  Future<Map> _cachedMap(String path) async => await _cached(path) as Map;
  Future<List<T>> _list<T>(
    String path,
    T Function(Map<String, dynamic>) fromJson,
  ) async => [for (final j in await api.get<List<dynamic>>(path)) fromJson(j)];

  f1() => _list('$_base/units', AdminUnit.fromJson);
  f2() => _cachedMap('/learn/topics/$id');
  f3() => api.get<List<dynamic>>(_base);
  f4() => api.post<Object?>(switch (kind) {
    NodeKind.unit => '$_base/units',
    NodeKind.topic => '$_base/units/$parentId/topics',
  }, data: fields);
}
""",
    )
    assert _found(tmp_path) == {
        ("GET", "/admin/syllabus/units"),
        ("GET", "/learn/topics/{}"),
        ("GET", "/admin/syllabus"),
        ("POST", "/admin/syllabus/units"),
        ("POST", "/admin/syllabus/units/{}/topics"),
    }


def test_unresolvable_argument_is_reported(tmp_path):
    _write(tmp_path, "apps/mobile/lib/a.dart", "f() => api.get<Object?>(buildUrl());")
    (call,) = scan_frontend(tmp_path)
    assert call.path.startswith("<unresolved")
    assert check([call], [], allowed={})[0].status == "unresolved"


OPENAPI = {
    "paths": {
        "/api/v1/auth/me": {"get": {}, "delete": {}},
        "/api/v1/posts/{post_id}": {"get": {}, "patch": {}},
        "/api/v1/files/{path:path}": {"get": {}},
        "/exam/papers": {"get": {}},  # legacy, outside /api/v1
    }
}


def _results(root: Path, allowed: dict | None = None) -> dict[tuple[str, str], str]:
    results = check(
        scan_frontend(root), load_routes(OPENAPI), allowed={} if allowed is None else allowed
    )
    return {(r.call.method, r.call.path): r.status for r in results}


def test_check_reports_missing_wrong_method_and_allowed(tmp_path):
    _write(
        tmp_path,
        "apps/mobile/lib/a.dart",
        """
a() => api.get('/auth/me');
b() => api.patch('/posts/$id');
c() => api.post('/posts/$id');
d() => api.get('/posts/$id/likes');
e() => api.get('/exam/papers');
f() => api.get('/files/visuals/a/b.png');
g() => api.get('/admin/analytics/$part');
""",
    )
    assert _results(tmp_path, {("GET", "/admin/analytics/{}"): "why"}) == {
        ("GET", "/auth/me"): "ok",
        ("PATCH", "/posts/{}"): "ok",
        ("POST", "/posts/{}"): "wrong-method",
        ("GET", "/posts/{}/likes"): "missing",
        ("GET", "/exam/papers"): "missing",
        ("GET", "/files/visuals/a/b.png"): "ok",
        ("GET", "/admin/analytics/{}"): "allowed",
    }


def test_route_param_matches_literal_but_dart_param_never_matches_literal(tmp_path):
    _write(
        tmp_path,
        "apps/mobile/lib/a.dart",
        "a() => api.get('/posts/latest');\nb() => api.delete('/auth/$who');",
    )
    assert _results(tmp_path) == {("GET", "/posts/latest"): "ok", ("DELETE", "/auth/{}"): "missing"}


def test_stale_allow_list_entries_are_listed(tmp_path):
    _write(tmp_path, "apps/mobile/lib/a.dart", "a() => api.get('/auth/me');")
    allowed = {("GET", "/gone/{}"): "old"}
    results = check(scan_frontend(tmp_path), load_routes(OPENAPI), allowed=allowed)
    assert stale_allow_list(results, allowed) == [("GET", "/gone/{}")]


# --------------------------------------------------------------------------- CLI (real app)


def test_main_exit_codes(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2

    _write(tmp_path, "apps/mobile/lib/ok.dart", "a() => api.get('/auth/me');")
    assert main([str(tmp_path)]) == 0

    _write(tmp_path, "apps/mobile/lib/bad.dart", "b() => api.get('/no/such/route');")
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "GET    /no/such/route" in out
    assert "apps/mobile/lib/bad.dart:1" in out


def test_main_requires_the_frontend_argument():
    with pytest.raises(SystemExit):
        main([])


@pytest.mark.skipif(not FRONTEND.is_dir(), reason="frontend repo not cloned next to this one")
def test_real_frontend_has_no_gaps(capsys):
    assert main([str(FRONTEND)]) == 0, capsys.readouterr().out
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("note:")]


def test_allow_list_entries_explain_themselves():
    assert all(reason.strip() for reason in ALLOWED_UNMATCHED.values())
